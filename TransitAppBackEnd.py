import os
import time
import math
import csv
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine, Column, Float, String, Integer, DateTime, JSON
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

# --- load environment ---
load_dotenv()

# --- config ---
DB_URL = os.getenv("TRANSIT_DB", "sqlite:///transit.db")
GTFS_DIR = os.getenv("GTFS_DIR", "./gtfs_static")
TRIP_UPDATES_URL = os.getenv("TRIP_UPDATES_URL")
VEHICLE_POSITIONS_URL = os.getenv("VEHICLE_POSITIONS_URL")
ALERTS_URL = os.getenv("ALERTS_URL")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "12"))
REPORT_DECAY_SECONDS = int(os.getenv("REPORT_DECAY_SECONDS", "600"))

# --- DB setup ---
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class Stop(Base):
    __tablename__ = "stops"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    meta = Column(JSON, default={})

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    stop_id = Column(String, index=True)
    line_id = Column(String, index=True)
    arrival_seconds = Column(Integer)
    mode = Column(String, default="transit")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    extra = Column(JSON, default={})

Base.metadata.create_all(bind=engine)

# --- Pydantic models ---
class ReportIn(BaseModel):
    stop_id: str
    line_id: str
    arrival_seconds: int
    mode: Optional[str] = "transit"
    lat: Optional[float] = None
    lng: Optional[float] = None
    extra: Optional[dict] = {}

class StopOut(BaseModel):
    id: str
    name: str
    lat: float
    lng: float

class ETAOut(BaseModel):
    stop_id: str
    line_id: Optional[str]
    eta_seconds: int
    source: str
    details: dict

# --- util functions ---
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def weighted_avg_reports(reports):
    if not reports:
        return None
    total_w, total = 0.0, 0.0
    for arrival, age in reports:
        w = math.exp(-age / max(1, REPORT_DECAY_SECONDS))
        total_w += w
        total += arrival * w
    return int(total / total_w) if total_w > 0 else None

# --- static GTFS ---
STOPS_STATIC, ROUTES_STATIC, TRIPS_STATIC, STOP_TIMES_BY_STOP = {}, {}, {}, {}

def _t2s(t):
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s

def _now_sec_local():
    d = datetime.now()
    return d.hour * 3600 + d.minute * 60 + d.second

def load_static_gtfs():
    p = Path(GTFS_DIR)
    with open(p/"stops.txt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            STOPS_STATIC[r["stop_id"]] = {"name": r["stop_name"], "lat": float(r["stop_lat"]), "lng": float(r["stop_lon"])}
    with open(p/"routes.txt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ROUTES_STATIC[r["route_id"]] = {"short": r.get("route_short_name") or "", "long": r.get("route_long_name") or ""}
    with open(p/"trips.txt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            TRIPS_STATIC[r["trip_id"]] = {"route_id": r["route_id"]}
    with open(p/"stop_times.txt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            STOP_TIMES_BY_STOP.setdefault(r["stop_id"], []).append(
                {"trip_id": r["trip_id"], "arr_sec": _t2s(r["arrival_time"]), "seq": int(r["stop_sequence"])}
            )
    for lst in STOP_TIMES_BY_STOP.values():
        lst.sort(key=lambda x: x["arr_sec"])
try:
    load_static_gtfs()
except Exception as e:
    print("GTFS load failed:", e)

# seed DB stops
with SessionLocal() as db:
    if not db.query(Stop).first():
        for sid, s in list(STOPS_STATIC.items())[:300]:
            db.add(Stop(id=sid, name=s["name"], lat=s["lat"], lng=s["lng"]))
        db.commit()

# --- realtime caches ---
TRIP_DELAY, TRIP_STOP_DELAY, VEHICLES, ALERTS = {}, {}, [], []

def _fetch_pb(url):
    r = requests.get(url, timeout=6)
    r.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(r.content)
    return feed

def poll_trip_updates():
    if not TRIP_UPDATES_URL: return
    feed = _fetch_pb(TRIP_UPDATES_URL)
    td, tsd = {}, {}
    for ent in feed.entity:
        tu = ent.trip_update
        if not tu or not tu.trip.trip_id: continue
        tid = tu.trip.trip_id
        for su in tu.stop_time_update:
            sid, d = su.stop_id, None
            if su.arrival and su.arrival.HasField("delay"): d = su.arrival.delay
            elif su.departure and su.departure.HasField("delay"): d = su.departure.delay
            if sid and d is not None: tsd[(tid, sid)] = d
        d0 = 0
        for su in tu.stop_time_update:
            if su.arrival and su.arrival.HasField("delay"): d0 = su.arrival.delay; break
            if su.departure and su.departure.HasField("delay"): d0 = su.departure.delay; break
        td[tid] = d0
    TRIP_DELAY.clear(); TRIP_DELAY.update(td)
    TRIP_STOP_DELAY.clear(); TRIP_STOP_DELAY.update(tsd)

def poll_vehicle_positions():
    if not VEHICLE_POSITIONS_URL: return
    feed = _fetch_pb(VEHICLE_POSITIONS_URL)
    rows = []
    for ent in feed.entity:
        v = ent.vehicle
        if not v or not v.position: continue
        rows.append({
            "vehicle_id": (v.vehicle.id if v.vehicle and v.vehicle.id else ent.id),
            "trip_id": v.trip.trip_id if v.trip and v.trip.trip_id else None,
            "lat": v.position.latitude,
            "lng": v.position.longitude,
            "bearing": v.position.bearing if v.position.HasField("bearing") else None,
            "stop_id": v.stop_id if v.HasField("stop_id") else None
        })
    VEHICLES.clear(); VEHICLES.extend(rows)

def poll_alerts():
    if not ALERTS_URL: return
    feed = _fetch_pb(ALERTS_URL)
    rows = []
    for ent in feed.entity:
        a = ent.alert
        if not a: continue
        header = a.header_text.translation[0].text if a.header_text.translation else ""
        desc = a.description_text.translation[0].text if a.description_text.translation else ""
        rows.append({"id": ent.id, "header": header, "desc": desc})
    ALERTS.clear(); ALERTS.extend(rows)

def poll_realtime_loop():
    while True:
        try:
            poll_trip_updates()
            poll_vehicle_positions()
            poll_alerts()
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SECONDS)

t = threading.Thread(target=poll_realtime_loop, daemon=True)
t.start()

# --- helpers for /eta ---
def next_arrivals_for_stop(stop_id, line_id=None, limit=8):
    now = _now_sec_local()
    rows = []
    for st in STOP_TIMES_BY_STOP.get(stop_id, []):
        trip = TRIPS_STATIC.get(st["trip_id"])
        if not trip: continue
        r_id = trip["route_id"]
        delay = TRIP_STOP_DELAY.get((st["trip_id"], stop_id), TRIP_DELAY.get(st["trip_id"], 0))
        eta = st["arr_sec"] + delay - now
        if eta > -120:
            rows.append({"trip_id": st["trip_id"], "route_id": r_id, "delay": delay, "eta": eta})
    rows.sort(key=lambda x: x["eta"])
    return rows[:limit]

# --- FastAPI app ---
app = FastAPI(title="UW Transit Backend")

@app.post("/report", status_code=201)
def create_report(r: ReportIn):
    with SessionLocal() as db:
        rep = Report(**r.dict(), timestamp=datetime.utcnow())
        db.add(rep)
        db.commit()
        db.refresh(rep)
        return {"id": rep.id}

@app.get("/stops", response_model=List[StopOut])
def list_stops():
    with SessionLocal() as db:
        rows = db.query(Stop).all()
        return [StopOut(id=s.id, name=s.name, lat=s.lat, lng=s.lng) for s in rows]

@app.get("/eta", response_model=ETAOut)
def get_eta(stop_id: str, line_id: Optional[str] = None, origin_lat: Optional[float] = None, origin_lng: Optional[float] = None):
    now = datetime.utcnow()
    with SessionLocal() as db:
        stop = db.query(Stop).filter(Stop.id == stop_id).first()
        if not stop:
            raise HTTPException(status_code=404, detail="stop not found")

        q = db.query(Report).filter(Report.stop_id == stop_id)
        if line_id: q = q.filter(Report.line_id == line_id)
        recent_cutoff = now - timedelta(seconds=REPORT_DECAY_SECONDS * 2)
        reports = q.filter(Report.timestamp >= recent_cutoff).all()
        rep_list = [(r.arrival_seconds, (now - r.timestamp).total_seconds()) for r in reports]
        crowd_eta = weighted_avg_reports(rep_list)

        live_eta = None
        cand = next_arrivals_for_stop(stop_id, line_id, limit=1)
        if cand:
            c = cand[0]
            live_eta = max(0, int(round(c["eta"])))

        combined_eta, source = None, "schedule"
        details = {"crowd_count": len(rep_list)}
        if crowd_eta is not None:
            combined_eta, source = crowd_eta, "crowd"
            details["crowd_eta"] = crowd_eta
        if live_eta is not None:
            if combined_eta is None:
                combined_eta, source = live_eta, "live_feed"
            else:
                combined_eta = int((combined_eta * 0.4) + (live_eta * 0.6))
                source = "crowd+live"
            details["live_eta"] = live_eta

        if combined_eta is None:
            headway = 10 * 60
            sec = int(time.time())
            next_arrival = ((sec // headway) + 1) * headway
            combined_eta = next_arrival - sec
            details["assumed_headway"] = headway

        return ETAOut(stop_id=stop_id, line_id=line_id, eta_seconds=combined_eta, source=source, details=details)

@app.get("/vehicles")
def vehicles(): return VEHICLES

@app.get("/alerts")
def alerts(): return ALERTS

try:
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
except Exception:
    pass