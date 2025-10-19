import os
import time
import math
import threading
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import sessionmaker, declarative_base





from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    DateTime,
    JSON,
    func,
    select,
)

# --- config ---
DB_URL = os.getenv("TRANSIT_DB", "sqlite:///transit.db")
LIVE_FEED_URL = os.getenv("LOCAL_TRANSIT_API_URL")  # e.g. "https://your-transit-api.local/vehicles"
LIVE_GTFS_RT_URL = os.getenv("LIVE_GTFS_RT_URL", "http://api.pugetsound.onebusaway.org/api/gtfs_realtime/vehicle-positions-for-agency/40.pb")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
REPORT_DECAY_SECONDS = int(os.getenv("REPORT_DECAY_SECONDS", "600"))  # weight decay window

# --- DB setup ---
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class Stop(Base):
    __tablename__ = "stops"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    # optional known schedules or route info could go here
    meta = Column(JSON, default={})


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    stop_id = Column(Integer, index=True)
    line_id = Column(String, index=True)  # e.g. "22" or "LINK_RED"
    arrival_seconds = Column(Integer)  # seconds until arrival from report time
    mode = Column(String, default="transit")  # walking, biking, transit
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    extra = Column(JSON, default={})


class LiveUpdate(Base):
    __tablename__ = "live_updates"
    id = Column(Integer, primary_key=True)
    fetched_at = Column(DateTime, default=datetime.utcnow, index=True)
    payload = Column(JSON)  # raw feed payload for lookup


Base.metadata.create_all(bind=engine)

# --- Pydantic models ---
class ReportIn(BaseModel):
    stop_id: int
    line_id: str
    arrival_seconds: int
    mode: Optional[str] = "transit"
    lat: Optional[float] = None
    lng: Optional[float] = None
    extra: Optional[dict] = {}


class StopOut(BaseModel):
    id: int
    name: str
    lat: float
    lng: float


class ETAOut(BaseModel):
    stop_id: int
    line_id: Optional[str]
    eta_seconds: int
    source: str  # "crowd", "live_feed", "schedule", "estimate"
    details: dict


# --- Utilities ---
def haversine_km(lat1, lon1, lat2, lon2):
    # returns distance in kilometers
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def weighted_avg_reports(reports):
    # reports: list of (arrival_seconds, age_seconds)
    # weight = exp(-age / REPORT_DECAY_SECONDS)
    if not reports:
        return None
    total_w = 0.0
    total = 0.0
    for arrival, age in reports:
        w = math.exp(-age / max(1, REPORT_DECAY_SECONDS))
        total_w += w
        total += arrival * w
    return int(total / total_w) if total_w > 0 else None


# --- Live feed polling ---
def poll_live_feed_loop():
    # If neither JSON feed nor GTFS-RT URL is configured, nothing to poll
    if not LIVE_FEED_URL and not LIVE_GTFS_RT_URL:
        return

    # Try to import GTFS realtime protobuf bindings if available
    gtfsrt_parser = None
    try:
        from google.transit import gtfs_realtime_pb2
        gtfsrt_parser = gtfs_realtime_pb2
    except Exception:
        gtfsrt_parser = None

    while True:
        now = datetime.utcnow()
        # First, try JSON-style feed if provided
        if LIVE_FEED_URL:
            try:
                resp = requests.get(LIVE_FEED_URL, timeout=5)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw": resp.text}
                    with SessionLocal() as db:
                        upd = LiveUpdate(payload={"source": "json_feed", "fetched_at": now.isoformat(), "data": data}, fetched_at=now)
                        db.add(upd)
                        db.commit()
            except Exception:
                # silence - in production you'd log
                pass

        # Next, try GTFS-Realtime protobuf feed
        if LIVE_GTFS_RT_URL:
            try:
                resp = requests.get(LIVE_GTFS_RT_URL, timeout=5)
                if resp.status_code == 200 and resp.content:
                    parsed = None
                    # If gtfs bindings available, parse protobuf to dict
                    if gtfsrt_parser:
                        try:
                            feed = gtfsrt_parser.FeedMessage()
                            feed.ParseFromString(resp.content)
                            # convert to JSON-friendly structure
                            parsed = {"header": {"gtfs_realtime_version": getattr(feed.header, "gtfs_realtime_version", None), "timestamp": getattr(feed.header, "timestamp", None)}, "entities": []}
                            for ent in feed.entity:
                                e = {"id": ent.id}
                                if ent.HasField("vehicle"):
                                    v = ent.vehicle
                                    vj = {}
                                    # copy a few common fields
                                    if v.trip and v.trip.trip_id:
                                        vj["trip_id"] = v.trip.trip_id
                                    if v.trip and v.trip.route_id:
                                        vj["route_id"] = v.trip.route_id
                                    if v.vehicle and v.vehicle.id:
                                        vj["vehicle_id"] = v.vehicle.id
                                    if v.position:
                                        vj["position"] = {"lat": v.position.latitude, "lon": v.position.longitude, "speed": getattr(v.position, "speed", None)}
                                    if v.current_stop_sequence:
                                        vj["current_stop_sequence"] = v.current_stop_sequence
                                    if v.stop_id:
                                        vj["stop_id"] = v.stop_id
                                    if v.timestamp:
                                        vj["timestamp"] = v.timestamp
                                    e["vehicle"] = vj
                                parsed["entities"].append(e)
                        except Exception:
                            parsed = {"raw_bytes_length": len(resp.content)}
                    else:
                        # No protobuf parser available; store raw bytes length and note it's protobuf
                        parsed = {"raw_bytes_length": len(resp.content), "note": "protobuf_not_parsed"}

                    with SessionLocal() as db:
                        upd = LiveUpdate(payload={"source": "gtfs_rt", "fetched_at": now.isoformat(), "data": parsed}, fetched_at=now)
                        db.add(upd)
                        db.commit()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL_SECONDS)


# --- App ---
app = FastAPI(title="Transit Backend (crowd + live feed)")

# start background poller thread at import/run time if any feed URL is present
if LIVE_FEED_URL or LIVE_GTFS_RT_URL:
    t = threading.Thread(target=poll_live_feed_loop, daemon=True)
    t.start()


@app.post("/report", status_code=201)
def create_report(r: ReportIn):
    with SessionLocal() as db:
        rep = Report(
            stop_id=r.stop_id,
            line_id=r.line_id,
            arrival_seconds=r.arrival_seconds,
            mode=r.mode,
            lat=r.lat,
            lng=r.lng,
            extra=r.extra,
            timestamp=datetime.utcnow(),
        )
        db.add(rep)
        db.commit()
        db.refresh(rep)
        return {"id": rep.id}


@app.get("/stops", response_model=List[StopOut])
def list_stops():
    # return all stops; in a real app you'd page this
    with SessionLocal() as db:
        rows = db.query(Stop).all()
        return [StopOut(id=s.id, name=s.name, lat=s.lat, lng=s.lng) for s in rows]


@app.post("/stops", status_code=201)
def create_stop(s: StopOut):
    with SessionLocal() as db:
        st = Stop(id=s.id, name=s.name, lat=s.lat, lng=s.lng)
        db.add(st)
        db.commit()
        return {"id": st.id}


@app.get("/eta", response_model=ETAOut)
def get_eta(
    stop_id: int = Query(...),
    line_id: Optional[str] = Query(None),
    mode: str = Query("transit"),  # walking, biking, transit
    origin_lat: Optional[float] = Query(None),
    origin_lng: Optional[float] = Query(None),
):
    """
    Compute ETA to a stop (and optionally for a specific line).
    Algorithm:
    - If users have recent reports for stop+line, compute weighted average (by recency).
    - If live feed has data for that stop/line, incorporate it.
    - If origin provided and mode is walking/biking, add walking/biking time to reach stop.
    - Fallback to schedule-based estimate (simple periodic schedule) if no real data.
    """
    now = datetime.utcnow()
    with SessionLocal() as db:
        stop = db.query(Stop).filter(Stop.id == stop_id).first()
        if not stop:
            raise HTTPException(status_code=404, detail="stop not found")

        # collect recent reports (stop +/- line if provided)
        q = db.query(Report).filter(Report.stop_id == stop_id)
        if line_id:
            q = q.filter(Report.line_id == line_id)
        recent_cutoff = now - timedelta(seconds=REPORT_DECAY_SECONDS * 2)
        reports = q.filter(Report.timestamp >= recent_cutoff).all()

        rep_list = []
        for r in reports:
            age = (now - r.timestamp).total_seconds()
            rep_list.append((r.arrival_seconds, age))

        crowd_eta = weighted_avg_reports(rep_list)

        # check latest live feed
        live_eta = None
        live_payload = None
        latest_live = db.query(LiveUpdate).order_by(LiveUpdate.fetched_at.desc()).first()
        if latest_live and latest_live.payload:
            # payload format depends on transit agency; try to find an arrival for stop+line
            payload = latest_live.payload
            # store raw payload in details if used
            live_payload = payload
            # Attempt a few common shapes in payload
            # Example: payload might have "arrivals": [{"stop_id":..., "line":..., "eta_seconds":...}, ...]
            items = []
            if isinstance(payload, dict):
                items = payload.get("arrivals") or payload.get("predictions") or payload.get("vehicles") or []
            if isinstance(items, list):
                for it in items:
                    try:
                        sid = str(it.get("stop_id") or it.get("stop"))
                        lid = str(it.get("line") or it.get("route") or it.get("route_id") or it.get("trip_short_name"))
                        eta = it.get("eta_seconds") or it.get("arrival_in_seconds") or it.get("arrival_seconds")
                        if eta is None:
                            continue
                        if str(sid) == str(stop_id) and (not line_id or str(lid) == str(line_id)):
                            live_eta = int(eta)
                            break
                    except Exception:
                        continue

        # Combine sources: prefer crowd if multiple recent reports, otherwise live, else schedule
        source = "schedule"
        combined_eta = None
        details = {"crowd_count": len(rep_list)}
        if crowd_eta is not None:
            combined_eta = crowd_eta
            source = "crowd"
            details["crowd_eta"] = crowd_eta
        if live_eta is not None:
            # weigh live slightly higher if crowd is old or absent
            if combined_eta is None:
                combined_eta = live_eta
                source = "live_feed"
            else:
                # simple fusion: average with preference to lower latency (assume live fresher)
                combined_eta = int((combined_eta * 0.4) + (live_eta * 0.6))
                source = "crowd+live"
            details["live_eta"] = live_eta
            details["live_sample"] = live_payload if live_payload and len(str(live_payload)) < 2000 else None

        if combined_eta is None:
            # fallback schedule: assume regular headway (e.g., every 10 minutes)
            headway = 10 * 60  # seconds
            # simple deterministic schedule: next arrival occurs at nearest multiple of headway from epoch
            seconds_since_epoch = int(time.time())
            next_arrival = ((seconds_since_epoch // headway) + 1) * headway
            combined_eta = max(0, next_arrival - seconds_since_epoch)
            source = "schedule"
            details["assumed_headway_seconds"] = headway

        # Add walking/biking time from origin to stop if requested
        walk_bike_seconds = 0
        if origin_lat is not None and origin_lng is not None:
            dist_km = haversine_km(origin_lat, origin_lng, stop.lat, stop.lng)
            if mode == "walking":
                speed_kmh = 5.0
            elif mode == "biking":
                speed_kmh = 15.0
            else:
                # mode transit: assume walking to stop
                speed_kmh = 5.0
            walk_time_hours = dist_km / max(0.001, speed_kmh)
            walk_bike_seconds = int(walk_time_hours * 3600)
            details["origin_distance_km"] = round(dist_km, 3)
            details["walk_bike_seconds"] = walk_bike_seconds

        # For transit preference add waiting time (combined_eta) after walking to stop
        if mode in ("walking", "biking"):
            eta_seconds = walk_bike_seconds  # arrive at destination by walking/biking; user may want door-to-door
            # If they asked for transit but prefer walking/biking, could compute both; here we assume they want travel time to stop.
            source = source if source != "schedule" else ("estimate" if walk_bike_seconds else "schedule")
        else:
            # transit mode: walking time to stop (if provided) plus transit arrival
            eta_seconds = combined_eta + walk_bike_seconds

        return ETAOut(
            stop_id=stop_id,
            line_id=line_id,
            eta_seconds=int(max(0, eta_seconds)),
            source=source,
            details=details,
        )


    # Serve the static frontend (if present) at the root path
    # The `static` directory will contain `index.html`, `app.js`, etc.
    try:
        app.mount("/", StaticFiles(directory="static", html=True), name="static")
    except Exception:
        # If StaticFiles can't be mounted for any reason, ignore so backend still works
        pass


@app.get('/routes')
def list_routes():
    # Return all routes from the `routes` table if present
    with SessionLocal() as db:
        try:
            rows = db.execute(select(["id", "short_name", "long_name", "route_type"]).select_from("routes")).fetchall()
        except Exception:
            # routes table may not exist
            return []
        out = []
        for r in rows:
            out.append({
                'id': r[0],
                'short_name': r[1],
                'long_name': r[2],
                'route_type': r[3],
            })
        return out


@app.get('/routes/{route_id}/stops')
def route_stops(route_id: str):
    # Return ordered stops for a route by joining route_stops -> stops
    with SessionLocal() as db:
        try:
            rows = db.execute(
                "SELECT rs.stop_sequence, s.id, s.name, s.lat, s.lng FROM route_stops rs JOIN stops s ON rs.stop_id = s.id WHERE rs.route_id = ? ORDER BY rs.stop_sequence",
                (route_id,)
            ).fetchall()
        except Exception:
            return []
        return [
            {"sequence": r[0], "id": r[1], "name": r[2], "lat": r[3], "lng": r[4]} for r in rows
        ]