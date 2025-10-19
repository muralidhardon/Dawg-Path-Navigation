import os
import csv
import math
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import requests
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# Optional realtime
from google.transit import gtfs_realtime_pb2

load_dotenv()

# ----------------------------
# Config
# ----------------------------
GTFS_DIR = os.getenv("GTFS_DIR", "./gtfs_static")
TRIP_UPDATES_URL = os.getenv("TRIP_UPDATES_URL", "")    # optional
MAX_WALK_METERS_DEFAULT = int(os.getenv("MAX_WALK_METERS", "800"))  # ~10 min walk

# ----------------------------
# Helpers
# ----------------------------
def t2s(t: str) -> int:
    # "HH:MM:SS" -> seconds since midnight (supports 24+ hours like "25:10:00")
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s

def s2t(s: int) -> str:
    # seconds since midnight -> "HH:MM"
    s = max(0, s)
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"

def now_local_sec() -> int:
    d = datetime.now()
    return d.hour * 3600 + d.minute * 60 + d.second

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ----------------------------
# Load static GTFS (minimal indexes)
# ----------------------------
STOPS: Dict[str, Dict[str, Any]] = {}
ROUTES: Dict[str, Dict[str, Any]] = {}
TRIPS: Dict[str, Dict[str, Any]] = {}
STOP_TIMES_BY_TRIP: Dict[str, List[Dict[str, Any]]] = {}
STOP_TIMES_BY_STOP: Dict[str, List[Dict[str, Any]]] = {}
ROUTES_BY_STOP: Dict[str, set] = {}           # stop_id -> {route_id}
TRIPS_BY_ROUTE: Dict[str, List[str]] = {}     # route_id -> [trip_id]

def load_static():
    p = Path(GTFS_DIR)
    assert (p/"stops.txt").exists(), f"stops.txt not found in {p}"
    def read(name):
        with open(p/name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    for r in read("stops.txt"):
        STOPS[r["stop_id"]] = {
            "name": r["stop_name"],
            "lat": float(r["stop_lat"]),
            "lon": float(r["stop_lon"])
        }

    for r in read("routes.txt"):
        ROUTES[r["route_id"]] = {
            "short": r.get("route_short_name") or "",
            "long": r.get("route_long_name") or "",
            "type": r.get("route_type")
        }

    for r in read("trips.txt"):
        TRIPS[r["trip_id"]] = {
            "route_id": r["route_id"],
            "service_id": r["service_id"],
            "shape_id": r.get("shape_id")
        }
        TRIPS_BY_ROUTE.setdefault(r["route_id"], []).append(r["trip_id"])

    # stop_times (both per-trip and per-stop views)
    for r in read("stop_times.txt"):
        trip_id = r["trip_id"]
        stop_id = r["stop_id"]
        row = {
            "trip_id": trip_id,
            "stop_id": stop_id,
            "arr_sec": t2s(r["arrival_time"]),
            "dep_sec": t2s(r["departure_time"]),
            "seq": int(r["stop_sequence"])
        }
        STOP_TIMES_BY_TRIP.setdefault(trip_id, []).append(row)
        STOP_TIMES_BY_STOP.setdefault(stop_id, []).append(row)
        ROUTES_BY_STOP.setdefault(stop_id, set()).add(TRIPS[trip_id]["route_id"])

    # sort for efficient scans
    for lst in STOP_TIMES_BY_TRIP.values():
        lst.sort(key=lambda x: x["seq"])
    for lst in STOP_TIMES_BY_STOP.values():
        lst.sort(key=lambda x: x["arr_sec"])

load_static()

# ----------------------------
# Optional Realtime Delays (TripUpdates)
# ----------------------------
TRIP_DELAY: Dict[str, int] = {}                 # trip_id -> delay seconds
TRIP_STOP_DELAY: Dict[Tuple[str, str], int] = {} # (trip_id, stop_id) -> delay seconds

def fetch_trip_updates():
    if not TRIP_UPDATES_URL:
        TRIP_DELAY.clear(); TRIP_STOP_DELAY.clear()
        return
    try:
        r = requests.get(TRIP_UPDATES_URL, timeout=6)
        r.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(r.content)
        td, tsd = {}, {}
        for ent in feed.entity:
            tu = ent.trip_update
            if not tu or not tu.trip.trip_id:
                continue
            tid = tu.trip.trip_id
            # per-stop delays if present
            for su in tu.stop_time_update:
                sid, d = su.stop_id, None
                if su.arrival and su.arrival.HasField("delay"): d = su.arrival.delay
                elif su.departure and su.departure.HasField("delay"): d = su.departure.delay
                if sid and d is not None: tsd[(tid, sid)] = d
            # trip-level delay fallback (first)
            d0 = 0
            for su in tu.stop_time_update:
                if su.arrival and su.arrival.HasField("delay"): d0 = su.arrival.delay; break
                if su.departure and su.departure.HasField("delay"): d0 = su.departure.delay; break
            td[tid] = d0
        TRIP_DELAY.clear(); TRIP_DELAY.update(td)
        TRIP_STOP_DELAY.clear(); TRIP_STOP_DELAY.update(tsd)
    except Exception:
        # Ignore realtime failures (planner still works with schedules)
        pass

# Call once at start; client can request a refresh via query flag if desired
try:
    fetch_trip_updates()
except Exception:
    pass

# ----------------------------
# Planning models
# ----------------------------
class Leg(BaseModel):
    mode: str                      # "WALK" | "TRANSIT"
    from_name: str
    to_name: str
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float
    route: Optional[str] = None    # for transit
    trip_id: Optional[str] = None  # for transit
    dep_time: Optional[str] = None
    arr_time: Optional[str] = None
    duration_sec: int

class Itinerary(BaseModel):
    duration_sec: int
    depart_time: str
    arrive_time: str
    transfers: int
    legs: List[Leg]
    notes: Optional[str] = None

# ----------------------------
# Core planning logic
#   Strategy: 
#     - nearest origin stops (within walk cap)
#     - nearest destination stops (within walk cap)
#     - DIRECT: same route connects origin-stop to dest-stop (no transfer)
#     - ONE-TRANSFER: origin route X to an interchange stop then route Y to dest
#   This is deliberately simple & hackathon-friendly.
# ----------------------------
def nearest_stops(lat: float, lon: float, limit=10, max_m=MAX_WALK_METERS_DEFAULT):
    rows = []
    for sid, s in STOPS.items():
        d = haversine_m(lat, lon, s["lat"], s["lon"])
        if d <= max_m:
            rows.append((sid, d))
    rows.sort(key=lambda x: x[1])
    return rows[:limit]

def find_direct_trips(o_stop: str, d_stop: str, depart_after_sec: int, rt_delays=True) -> List[Dict[str, Any]]:
    """Return candidate direct rides (same trip passes both stops with o_seq < d_seq)."""
    candidates = []
    # Intersect routes that serve both stops (fast filter)
    common_routes = ROUTES_BY_STOP.get(o_stop, set()) & ROUTES_BY_STOP.get(d_stop, set())
    for route_id in common_routes:
        for trip_id in TRIPS_BY_ROUTE.get(route_id, []):
            seqs = STOP_TIMES_BY_TRIP.get(trip_id)
            if not seqs: continue
            # find o and d entries
            o_row = next((r for r in seqs if r["stop_id"] == o_stop), None)
            d_row = next((r for r in seqs if r["stop_id"] == d_stop), None)
            if not o_row or not d_row or o_row["seq"] >= d_row["seq"]:
                continue
            # live delay (per-stop preferred)
            delay_o = TRIP_STOP_DELAY.get((trip_id, o_stop), TRIP_DELAY.get(trip_id, 0)) if rt_delays else 0
            delay_d = TRIP_STOP_DELAY.get((trip_id, d_stop), TRIP_DELAY.get(trip_id, 0)) if rt_delays else 0
            dep = o_row["dep_sec"] + delay_o
            arr = d_row["arr_sec"] + delay_d
            if dep >= depart_after_sec - 90:   # allow boarding slightly after requested time
                candidates.append({
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "dep": dep,
                    "arr": arr,
                    "o_row": o_row,
                    "d_row": d_row
                })
    candidates.sort(key=lambda x: x["arr"])
    return candidates

def build_walk_leg(name_a, lat_a, lon_a, name_b, lat_b, lon_b, speed_kmh=5.0) -> Leg:
    d_m = haversine_m(lat_a, lon_a, lat_b, lon_b)
    sec = int(d_m / (speed_kmh * 1000/3600))
    return Leg(
        mode="WALK",
        from_name=name_a, to_name=name_b,
        from_lat=lat_a, from_lng=lon_a,
        to_lat=lat_b, to_lng=lon_b,
        duration_sec=max(0, sec)
    )

def build_transit_leg(o_stop, d_stop, trip) -> Leg:
    rs = ROUTES[trip["route_id"]]
    rname = rs["short"] or rs["long"] or trip["route_id"]
    s_o, s_d = STOPS[o_stop], STOPS[d_stop]
    return Leg(
        mode="TRANSIT",
        from_name=f'{s_o["name"]} ({rname})',
        to_name=f'{s_d["name"]} ({rname})',
        from_lat=s_o["lat"], from_lng=s_o["lon"],
        to_lat=s_d["lat"], to_lng=s_d["lon"],
        route=rname,
        trip_id=trip["trip_id"],
        dep_time=s2t(trip["dep"]),
        arr_time=s2t(trip["arr"]),
        duration_sec=max(0, trip["arr"] - trip["dep"])
    )

def plan_direct(
    from_lat, from_lng, to_lat, to_lng,
    depart_after_sec, max_walk=MAX_WALK_METERS_DEFAULT, rt_delays=True
) -> List[Itinerary]:
    out = []
    near_o = nearest_stops(from_lat, from_lng, max_m=max_walk)
    near_d = nearest_stops(to_lat, to_lng, max_m=max_walk)
    if not near_o or not near_d:
        return []

    for o_stop, o_walk_m in near_o[:6]:
        for d_stop, d_walk_m in near_d[:6]:
            trips = find_direct_trips(o_stop, d_stop, depart_after_sec, rt_delays=rt_delays)[:2]
            for t in trips:
                walk1 = build_walk_leg("Origin", from_lat, from_lng, STOPS[o_stop]["name"], STOPS[o_stop]["lat"], STOPS[o_stop]["lon"])
                ride = build_transit_leg(o_stop, d_stop, t)
                walk2 = build_walk_leg(STOPS[d_stop]["name"], STOPS[d_stop]["lat"], STOPS[d_stop]["lon"], "Destination", to_lat, to_lng)
                depart_time = s2t(max(depart_after_sec, t["dep"] - walk1.duration_sec))
                arrive_time = s2t(t["arr"] + walk2.duration_sec)
                total = walk1.duration_sec + (t["arr"] - t["dep"]) + walk2.duration_sec
                out.append(Itinerary(
                    duration_sec=total,
                    depart_time=depart_time,
                    arrive_time=arrive_time,
                    transfers=0,
                    legs=[walk1, ride, walk2],
                    notes="Direct route"
                ))
    # sort fastest first
    out.sort(key=lambda i: i.duration_sec)
    # de-duplicate similar itineraries
    uniq, seen = [], set()
    for it in out:
        sig = (it.legs[1].route, it.depart_time, it.arrive_time)
        if sig in seen: continue
        uniq.append(it); seen.add(sig)
    return uniq[:5]

def plan_one_transfer(
    from_lat, from_lng, to_lat, to_lng,
    depart_after_sec, max_walk=MAX_WALK_METERS_DEFAULT, rt_delays=True
) -> List[Itinerary]:
    out = []
    near_o = nearest_stops(from_lat, from_lng, max_m=max_walk)
    near_d = nearest_stops(to_lat, to_lng, max_m=max_walk)
    if not near_o or not near_d: return []

    # build candidate origin/dest stops
    o_stops = [sid for sid,_ in near_o[:6]]
    d_stops = [sid for sid,_ in near_d[:6]]

    # Try: origin stop -> X (transfer) -> dest stop
    # Use stops that serve many routes as naive interchanges.
    # For speed, we’ll just test a small set: top 100 stops by route count or any in radius.
    interchanges = sorted(STOPS.keys(), key=lambda s: -len(ROUTES_BY_STOP.get(s, [])))[:100]

    for o_stop in o_stops:
        # first leg: try a few trips from origin to any interchange
        for x_stop in interchanges:
            if o_stop == x_stop: continue
            t1_list = find_direct_trips(o_stop, x_stop, depart_after_sec, rt_delays=rt_delays)[:2]
            if not t1_list: continue
            for t1 in t1_list:
                # buffer for transfer (min 2 minutes)
                transfer_ready = t1["arr"] + 120
                # second leg: X -> any destination stop
                for d_stop in d_stops:
                    t2_list = find_direct_trips(x_stop, d_stop, transfer_ready, rt_delays=rt_delays)[:1]
                    if not t2_list: continue
                    t2 = t2_list[0]
                    # Build legs
                    walk1 = build_walk_leg("Origin", from_lat, from_lng, STOPS[o_stop]["name"], STOPS[o_stop]["lat"], STOPS[o_stop]["lon"])
                    ride1 = build_transit_leg(o_stop, x_stop, t1)
                    ride2 = build_transit_leg(x_stop, d_stop, t2)
                    walk2 = build_walk_leg(STOPS[d_stop]["name"], STOPS[d_stop]["lat"], STOPS[d_stop]["lon"], "Destination", to_lat, to_lng)

                    depart_time = s2t(max(depart_after_sec, t1["dep"] - walk1.duration_sec))
                    arrive_time = s2t(t2["arr"] + walk2.duration_sec)
                    total = walk1.duration_sec + (t1["arr"] - t1["dep"]) + (t2["arr"] - t2["dep"]) + walk2.duration_sec
                    out.append(Itinerary(
                        duration_sec=total,
                        depart_time=depart_time,
                        arrive_time=arrive_time,
                        transfers=1,
                        legs=[walk1, ride1, ride2, walk2],
                        notes=f"Transfer at {STOPS[x_stop]['name']}"
                    ))
    out.sort(key=lambda i: i.duration_sec)
    # prune near-duplicates
    uniq, seen = [], set()
    for it in out:
        sig = (it.transfers, it.legs[1].route, it.legs[-2].route if it.transfers==1 else "", it.depart_time)
        if sig in seen: continue
        uniq.append(it); seen.add(sig)
    return uniq[:5]

# ----------------------------
# FastAPI service
# ----------------------------
app = FastAPI(title="Pure Navigation Planner")

@app.get("/health")
def health():
    return {
        "gtfs_loaded_stops": len(STOPS),
        "gtfs_loaded_routes": len(ROUTES),
        "gtfs_loaded_trips": len(TRIPS),
        "realtime": bool(TRIP_UPDATES_URL),
    }

@app.get("/plan", response_model=List[Itinerary])
def plan(
    from_lat: float = Query(...),
    from_lng: float = Query(...),
    to_lat: float = Query(...),
    to_lng: float = Query(...),
    depart_now: bool = Query(True),
    depart_time_s: Optional[int] = Query(None, description="seconds since midnight local"),
    max_transfers: int = Query(1, ge=0, le=1),
    max_walk_m: int = Query(MAX_WALK_METERS_DEFAULT, ge=100),
    use_realtime: bool = Query(True, description="use GTFS-RT TripUpdates if available"),
    refresh_rt: bool = Query(False, description="force pull latest TripUpdates this request"),
):
    if refresh_rt and use_realtime:
        fetch_trip_updates()

    depart_after = now_local_sec() if depart_now or not depart_time_s else int(depart_time_s)

    itineraries: List[Itinerary] = []
    # First try direct
    itineraries.extend(
        plan_direct(from_lat, from_lng, to_lat, to_lng, depart_after, max_walk=max_walk_m, rt_delays=(use_realtime and bool(TRIP_UPDATES_URL)))
    )
    # Then try one transfer if allowed and direct is sparse
    if max_transfers >= 1 and len(itineraries) < 3:
        itineraries.extend(
            plan_one_transfer(from_lat, from_lng, to_lat, to_lng, depart_after, max_walk=max_walk_m, rt_delays=(use_realtime and bool(TRIP_UPDATES_URL)))
        )

    if not itineraries:
        raise HTTPException(status_code=404, detail="No itinerary found within walking radius / schedule window.")

    return itineraries[:5]