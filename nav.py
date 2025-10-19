import os
import csv
import math
import time
import json
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

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
# Optional: per-road danger map (name/type → 1..10 danger score)
DANGER_MAP_PATH = os.getenv("DANGER_MAP_PATH", "./danger_map.json")
# Optional: circle-based safety zones (higher score = safer). Default to your circles file.
SAFETY_ZONES_PATH = os.getenv("SAFETY_ZONES_PATH", "./danger_zone.json")

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
    geometry: Optional[List[List[float]]] = None   # [[lng,lat], ...] GeoJSON-style for map drawing
    steps: Optional[List[Dict[str, Any]]] = None   # turn-by-turn steps for WALK legs
    safety_zones_score: Optional[float] = None     # 0..1 from circle zones file (if provided)
    safety_score: Optional[float] = None           # 0..1 combined (danger-map + zones)
    safety_matches: Optional[List[Dict[str, Any]]] = None  # evidence used to compute score
    # Optional: up to N alternative walking options (Mapbox), each with its own safety and duration
    alt_options: Optional[List[Dict[str, Any]]] = None
    walk_summary: Optional[str] = None   # brief Mapbox summary for the chosen walking path
# ----------------------------
# Real walking navigation (Mapbox Directions)
# ----------------------------

def fetch_walking_routes_mapbox(
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
    max_alts: int = 0,
) -> Optional[List[Dict[str, Any]]]:
    """
    Returns a list of up to (max_alts + 1) route dicts:
    { 'geometry': [[lng,lat], ...], 'steps': [...], 'duration_sec': int }
    First route is Mapbox's primary. Requires MAPBOX_TOKEN.
    """
    if not MAPBOX_TOKEN:
        return None
    try:
        # Use alternatives=true to request multiple candidate routes.
        url = (
            "https://api.mapbox.com/directions/v5/mapbox/walking/"
            f"{from_lng},{from_lat};{to_lng},{to_lat}"
            "?alternatives=true&overview=full&geometries=geojson&steps=true&language=en"
            f"&access_token={MAPBOX_TOKEN}"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return None
        out: List[Dict[str, Any]] = []
        for i, best in enumerate(routes):
            if i > max_alts:  # cap count: primary + max_alts
                break
            geom = best.get("geometry", {}).get("coordinates", [])
            duration_sec = int(best.get("duration", 0) or 0)
            summary = ""
            try:
                # Mapbox puts a human-readable summary on the first leg
                if best.get("legs"):
                    summary = best["legs"][0].get("summary") or ""
            except Exception:
                summary = ""
            steps: List[Dict[str, Any]] = []
            for leg in (best.get("legs") or []):
                for step in (leg.get("steps") or []):
                    steps.append({
                        "maneuver": step.get("maneuver", {}).get("instruction", ""),
                        "distance_m": step.get("distance", 0),
                        "duration_s": int(step.get("duration", 0) or 0),
                        "name": step.get("name", ""),
                    })
            out.append({"geometry": geom, "steps": steps, "duration_sec": duration_sec, "summary": summary})
        return out or None
    except Exception:
        return None

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
# Real walking navigation (Mapbox Directions)
# ----------------------------

def fetch_walking_directions_mapbox(
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
) -> Optional[Dict[str, Any]]:
    """
    Returns a dict with 'geometry' (list of [lng,lat]) and 'steps' (list of instructions),
    and 'duration_sec' if available. Uses Mapbox Directions API with geojson geometry.
    """
    if not MAPBOX_TOKEN:
        return None
    try:
        url = (
            "https://api.mapbox.com/directions/v5/mapbox/walking/"
            f"{from_lng},{from_lat};{to_lng},{to_lat}"
            "?alternatives=false&overview=full&geometries=geojson&steps=true&language=en"
            f"&access_token={MAPBOX_TOKEN}"
        )
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return None
        best = routes[0]
        geom = best.get("geometry", {}).get("coordinates", [])
        duration_sec = int(best.get("duration", 0))
        steps: List[Dict[str, Any]] = []
        for leg in (best.get("legs") or []):
            for step in (leg.get("steps") or []):
                # keep only essentials to keep payload small
                steps.append({
                    "maneuver": step.get("maneuver", {}).get("instruction", ""),
                    "distance_m": step.get("distance", 0),
                    "duration_s": int(step.get("duration", 0)),
                    "name": step.get("name", ""),
                })
        return {"geometry": geom, "steps": steps, "duration_sec": duration_sec}
    except Exception:
        # Fail soft: if directions fail, we simply return None and keep haversine estimate
        return None

# ----------------------------
# Danger map loader + scoring
#   Accepts JSON like:
#   {
#     "roads": {"Stevens Way NE": 2, "Memorial Way NE": 3},
#     "types": {"alley": 9, "arterial": 6, "trail": 2},
#     "default": 5
#   }
#   Danger scale: 1 (safest) .. 10 (most dangerous)
#   Safety score we compute: 1.0 .. 0.0  (1 - normalized danger)
# ----------------------------
DANGER_MAP: Dict[str, Any] = {"roads": {}, "types": {}, "default": 5}

def _load_danger_map():
    global DANGER_MAP
    p = Path(DANGER_MAP_PATH)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # normalize keys
        roads = { (k or "").strip().lower(): int(v) for k, v in (data.get("roads") or {}).items() }
        types = { (k or "").strip().lower(): int(v) for k, v in (data.get("types") or {}).items() }
        default = int(data.get("default", 5))
        DANGER_MAP = {"roads": roads, "types": types, "default": default}
    except Exception:
        # keep defaults on parse error
        DANGER_MAP = {"roads": {}, "types": {}, "default": 5}

def _danger_to_safety(danger: int) -> float:
    # Map 1..10 danger → 1..0 safety (linear)
    danger = max(1, min(10, int(danger)))
    return round(1.0 - (danger - 1) / 9.0, 3)

def _infer_type_from_name(name: str) -> Optional[str]:
    n = (name or "").lower()
    if "alley" in n: return "alley"
    if "trail" in n or "path" in n or "walk" in n: return "trail"
    if "way" in n: return "arterial"
    if "ave" in n or "avenue" in n or "st " in n or "street" in n or "blvd" in n: return "street"
    return None

def annotate_leg_from_danger_map(leg: 'Leg'):
    """
    Uses Mapbox steps (if present) to compute a safety score from your danger map.
    - For each step, look up an exact road-name match in DANGER_MAP["roads"].
    - Else try an inferred 'type' in DANGER_MAP["types"].
    - Else use DANGER_MAP["default"].
    The per-step safety is distance-weighted.
    """
    steps = leg.steps or []
    if not steps:
        # No steps (e.g., enhance_walk=false) → neutral score from default
        s = _danger_to_safety(DANGER_MAP.get("default", 5))
        leg.safety_score = s
        leg.safety_matches = [{"name": None, "danger": DANGER_MAP.get("default", 5), "safety": s, "distance_m": None}]
        return

    total_dist = 0.0
    weighted = 0.0
    matches: List[Dict[str, Any]] = []
    for st in steps:
        name = (st.get("name") or "").strip()
        dist = float(st.get("distance_m") or 0.0)
        key = name.lower()
        danger = DANGER_MAP["roads"].get(key)
        if danger is None:
            typ = _infer_type_from_name(name)
            if typ:
                danger = DANGER_MAP["types"].get(typ)
        if danger is None:
            danger = DANGER_MAP.get("default", 5)
        safety = _danger_to_safety(danger)
        matches.append({"name": name, "danger": int(danger), "safety": safety, "distance_m": dist})
        total_dist += dist
        weighted += safety * dist

    if total_dist <= 0:
        # fallback if distances missing
        if matches:
            avg = sum(m["safety"] for m in matches) / len(matches)
        else:
            avg = _danger_to_safety(DANGER_MAP.get("default", 5))
        leg.safety_score = round(avg, 3)
    else:
        leg.safety_score = round(weighted / total_dist, 3)
    leg.safety_matches = matches

# ----------------------------
# Safety Zones (circle areas with score 0..1)
#   File format:
#   { "zones": [ { "type":"circle","lat":..., "lng":..., "radius_m": 150, "score": 0.8, "label":"..." }, ... ] }
# ----------------------------
SAFETY_ZONES: Dict[str, Any] = {"zones": []}

def _load_safety_zones():
    global SAFETY_ZONES
    p = Path(SAFETY_ZONES_PATH)
    if not p.exists():
        SAFETY_ZONES = {"zones": []}
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        zones = data.get("zones") or []
        # basic validation/normalization
        norm = []
        for z in zones:
            if (z.get("type") or "circle").lower() != "circle":
                continue
            try:
                norm.append({
                    "lat": float(z["lat"]),
                    "lng": float(z["lng"]),
                    "radius_m": float(z.get("radius_m", 120)),
                    "score": max(0.0, min(1.0, float(z.get("score", 0.5)))),
                    "label": str(z.get("label") or "")
                })
            except Exception:
                continue
        SAFETY_ZONES = {"zones": norm}
    except Exception:
        SAFETY_ZONES = {"zones": []}

def _point_in_circle(lat: float, lng: float, center_lat: float, center_lng: float, radius_m: float) -> bool:
    return haversine_m(lat, lng, center_lat, center_lng) <= radius_m

def _zone_score_at(lat: float, lng: float) -> Optional[float]:
    """Return the highest zone score covering this point, or None if no zone."""
    best = None
    for z in SAFETY_ZONES.get("zones", []):
        if _point_in_circle(lat, lng, z["lat"], z["lng"], z["radius_m"]):
            s = float(z["score"])
            best = s if best is None else max(best, s)
    return best

def annotate_leg_from_zones(leg: 'Leg'):
    """
    Sample the walking geometry (or endpoints) against circle zones to compute a safety_zones_score.
    """
    samples: List[Tuple[float, float]] = []
    if leg.geometry:
        # geometry is [[lng,lat], ...]; downsample to keep it light
        for i, pt in enumerate(leg.geometry):
            if i % 4 == 0:
                samples.append((float(pt[1]), float(pt[0])))
    else:
        # fallback: endpoints + midpoint
        samples = [
            (leg.from_lat, leg.from_lng),
            ((leg.from_lat + leg.to_lat) / 2.0, (leg.from_lng + leg.to_lng) / 2.0),
            (leg.to_lat, leg.to_lng),
        ]
    values: List[float] = []
    evid: List[Dict[str, Any]] = []
    for (la, lo) in samples:
        s = _zone_score_at(la, lo)
        if s is not None:
            values.append(s)
            evid.append({"source": "zone", "lat": la, "lng": lo, "score": round(s, 3)})
    if values:
        leg.safety_zones_score = round(sum(values) / len(values), 3)
        # append to safety_matches evidence
        leg.safety_matches = (leg.safety_matches or []) + evid

# load danger map once
try:
    _load_danger_map()
except Exception:
    pass

# load safety zones once
try:
    _load_safety_zones()
except Exception:
    pass

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
        "mapbox_configured": bool(MAPBOX_TOKEN),
        "danger_map_loaded": Path(DANGER_MAP_PATH).exists(),
        "danger_roads_count": len(DANGER_MAP.get("roads", {})),
        "danger_types_count": len(DANGER_MAP.get("types", {})),
        "safety_zones_loaded": Path(SAFETY_ZONES_PATH).exists(),
        "safety_zones_count": len(SAFETY_ZONES.get("zones", [])),
    }

# --- Safety config endpoints ---
@app.get("/safety/config")
def safety_config():
    return {
        "zones_count": len(SAFETY_ZONES.get("zones", [])),
        "zones_path": str(Path(SAFETY_ZONES_PATH).resolve()),
        "danger_map_path": str(Path(DANGER_MAP_PATH).resolve())
    }

@app.post("/safety/reload")
def safety_reload():
    _load_safety_zones()
    return {"ok": True, "zones_count": len(SAFETY_ZONES.get("zones", []))}

@app.post("/danger/reload")
def danger_reload():
    _load_danger_map()
    return {"ok": True, "roads": len(DANGER_MAP.get("roads", {})), "types": len(DANGER_MAP.get("types", {}))}

# Nearby stops endpoint
@app.get("/nearby_stops")
def nearby_stops(
    lat: float = Query(..., description="latitude"),
    lng: float = Query(..., description="longitude"),
    limit: int = Query(10, ge=1, le=50),
    max_walk_m: int = Query(MAX_WALK_METERS_DEFAULT, ge=50, description="search radius in meters")
):
    """Return nearest GTFS stops to a point with distance and served routes."""
    results = []
    for sid, dist in nearest_stops(lat, lng, limit=limit, max_m=max_walk_m):
        s = STOPS[sid]
        routes = sorted(list(ROUTES_BY_STOP.get(sid, set())))
        results.append({
            "stop_id": sid,
            "name": s["name"],
            "lat": s["lat"],
            "lng": s["lon"],
            "distance_m": round(dist, 1),
            "routes": routes
        })
    return results

# Stop routes endpoint
@app.get("/stop_routes")
def stop_routes(stop_id: str = Query(..., description="GTFS stop_id")):
    """List route ids (and display names) that serve a stop."""
    if stop_id not in STOPS:
        raise HTTPException(status_code=404, detail="stop not found")
    out = []
    for rid in sorted(list(ROUTES_BY_STOP.get(stop_id, set()))):
        r = ROUTES.get(rid, {"short": "", "long": ""})
        out.append({"route_id": rid, "short_name": r.get("short") or "", "long_name": r.get("long") or ""})
    return out

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
    enhance_walk: bool = Query(False, description="if true, fetch real walking paths and steps"),
    walk_alternatives: int = Query(0, ge=0, le=5, description="If >0 and enhance_walk, attach up to N alternative walking routes per WALK leg"),
    safety: str = Query("off", regex="^(off|prefer|strict)$", description="Apply per-road safety bias using danger_map.json"),
    reject_walk_below: Optional[float] = Query(
        None, ge=0.0, le=1.0,
        description="If set (or if safety=strict with default), reject itineraries whose min WALK safety_score is below this value."
    ),
    allow_walk_only: bool = Query(True, description="If true, return a walk-only itinerary when no transit plan is found"),
    walk_only_max_m: int = Query(5000, ge=100, description="Max straight-line distance (meters) allowed for walk-only fallback"),
):
    if refresh_rt and use_realtime:
        fetch_trip_updates()

    depart_after = now_local_sec() if depart_now or not depart_time_s else int(depart_time_s)
    # If strict safety is requested and caller didn't set a threshold, use a sensible default
    if safety == "strict" and reject_walk_below is None:
        reject_walk_below = 0.40  # reject walks scored below 0.40 (≈ danger > ~7/10)

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
        # Optional walk-only fallback when no transit plan is found
        if allow_walk_only:
            # Use straight-line distance as a quick guard before asking Mapbox
            dist_m = haversine_m(from_lat, from_lng, to_lat, to_lng)
            if dist_m <= float(walk_only_max_m):
                # Try to fetch a real walking path (with optional alternatives) and score it
                routes = fetch_walking_routes_mapbox(
                    from_lat=from_lat, from_lng=from_lng,
                    to_lat=to_lat, to_lng=to_lng,
                    max_alts=walk_alternatives if enhance_walk and walk_alternatives > 0 else 0,
                )
                candidates: List[Dict[str, Any]] = []
                if routes:
                    for rt in routes:
                        tmp = Leg(
                            mode="WALK",
                            from_name="Origin", to_name="Destination",
                            from_lat=from_lat, from_lng=from_lng,
                            to_lat=to_lat, to_lng=to_lng,
                            duration_sec=int(rt.get("duration_sec") or max(1, int(dist_m / (5.0 * 1000/3600)))),
                            geometry=rt.get("geometry"),
                            steps=rt.get("steps"),
                            walk_summary=rt.get("summary") or None,
                        )
                        annotate_leg_from_danger_map(tmp)
                        annotate_leg_from_zones(tmp)
                        parts = [x for x in [tmp.safety_score, tmp.safety_zones_score] if x is not None]
                        if parts:
                            tmp.safety_score = round(sum(parts) / len(parts), 3)
                        biased = tmp.duration_sec
                        if safety in ("prefer", "strict") and tmp.safety_score is not None:
                            factor = 1.0 + (1.0 - tmp.safety_score) * (0.3 if safety == "prefer" else 0.6)
                            biased = int(biased * factor)
                        candidates.append({
                            "leg": tmp,
                            "biased": biased,
                        })
                else:
                    # No Mapbox or fetch failed — build a simple straight-line walk leg
                    tmp = build_walk_leg("Origin", from_lat, from_lng, "Destination", to_lat, to_lng)
                    annotate_leg_from_danger_map(tmp)
                    annotate_leg_from_zones(tmp)
                    parts = [x for x in [tmp.safety_score, tmp.safety_zones_score] if x is not None]
                    if parts:
                        tmp.safety_score = round(sum(parts) / len(parts), 3)
                    biased = tmp.duration_sec
                    if safety in ("prefer", "strict") and tmp.safety_score is not None:
                        factor = 1.0 + (1.0 - tmp.safety_score) * (0.3 if safety == "prefer" else 0.6)
                        biased = int(biased * factor)
                    candidates = [{"leg": tmp, "biased": biased}]

                # Choose the best walk option
                best = min(candidates, key=lambda c: c["biased"]) if candidates else None
                if best:
                    walk_leg = best["leg"]
                    # Respect strict safety rejection if configured
                    if reject_walk_below is not None and walk_leg.safety_score is not None and walk_leg.safety_score < float(reject_walk_below):
                        raise HTTPException(
                            status_code=404,
                            detail=f"Walk-only option rejected by safety filter (threshold={reject_walk_below}). Try lowering the threshold or using safety=prefer."
                        )
                    depart_after = now_local_sec() if depart_now or not depart_time_s else int(depart_time_s)
                    depart_time = s2t(depart_after)
                    arrive_time = s2t(depart_after + walk_leg.duration_sec)
                    it = Itinerary(
                        duration_sec=walk_leg.duration_sec,
                        depart_time=depart_time,
                        arrive_time=arrive_time,
                        transfers=0,
                        legs=[walk_leg],
                        notes="Walk-only fallback"
                    )
                    return [it]
        # No transit and no acceptable walk-only fallback
        raise HTTPException(status_code=404, detail="No itinerary found within walking radius / schedule window.")

    # Optionally enhance walking legs with real directions (Mapbox)
    if enhance_walk:
        for it in itineraries:
            for leg in it.legs:
                if leg.mode != "WALK":
                    continue
                # If alternatives requested, fetch multiple; else just the primary.
                routes = fetch_walking_routes_mapbox(
                    from_lat=leg.from_lat, from_lng=leg.from_lng,
                    to_lat=leg.to_lat, to_lng=leg.to_lng,
                    max_alts=walk_alternatives if walk_alternatives > 0 else 0
                )
                if not routes:
                    continue

                # Build candidate options with safety annotations and biased durations
                candidates: List[Dict[str, Any]] = []
                for rt in routes:
                    # Create a temporary leg to score this option
                    tmp = Leg(
                        mode="WALK",
                        from_name=leg.from_name, to_name=leg.to_name,
                        from_lat=leg.from_lat, from_lng=leg.from_lng,
                        to_lat=leg.to_lat, to_lng=leg.to_lng,
                        duration_sec=int(rt.get("duration_sec") or leg.duration_sec),
                        geometry=rt.get("geometry"),
                        steps=rt.get("steps"),
                        walk_summary=rt.get("summary") or None
                    )
                    # Safety annotations (danger map + zones)
                    annotate_leg_from_danger_map(tmp)
                    annotate_leg_from_zones(tmp)
                    # Combine sources if both exist
                    parts = [x for x in [tmp.safety_score, tmp.safety_zones_score] if x is not None]
                    if parts:
                        tmp.safety_score = round(sum(parts) / len(parts), 3)
                    # Compute biased duration according to safety mode (mirror later pipeline)
                    biased = tmp.duration_sec
                    if safety in ("prefer", "strict") and tmp.safety_score is not None:
                        if safety == "prefer":
                            factor = 1.0 + (1.0 - tmp.safety_score) * 0.3
                        else:
                            factor = 1.0 + (1.0 - tmp.safety_score) * 0.6
                        biased = int(biased * factor)
                    candidates.append({
                        "geometry": tmp.geometry,
                        "steps": tmp.steps,
                        "duration_sec": tmp.duration_sec,
                        "safety_score": tmp.safety_score,
                        "safety_zones_score": tmp.safety_zones_score,
                        "safety_matches": tmp.safety_matches,
                        "biased_duration_sec": biased,
                        "summary": tmp.walk_summary,
                    })

                # Choose the candidate with the smallest biased duration
                best = min(candidates, key=lambda c: c["biased_duration_sec"])
                # Set the chosen route onto the leg
                leg.geometry = best["geometry"]
                leg.steps = best["steps"]
                leg.duration_sec = best["duration_sec"]
                leg.safety_score = best["safety_score"]
                leg.safety_zones_score = best["safety_zones_score"]
                leg.safety_matches = best["safety_matches"]
                leg.walk_summary = best.get("summary")

                # Store remaining candidates as alternatives (excluding the chosen one)
                others = [c for c in candidates if c is not best]
                # Trim to at most walk_alternatives entries
                if walk_alternatives > 0 and others:
                    leg.alt_options = [
                        {
                            "geometry": c["geometry"],
                            "steps": c["steps"],
                            "duration_sec": c["duration_sec"],
                            "safety_score": c["safety_score"],
                            "safety_zones_score": c["safety_zones_score"],
                            "biased_duration_sec": c["biased_duration_sec"],
                            "summary": c.get("summary"),
                        }
                        for c in others[:walk_alternatives]
                    ]
                else:
                    leg.alt_options = None

    # --- Annotate safety for all WALK legs (zones + danger map), then optionally bias durations ---
    for it in itineraries:
        for leg in it.legs:
            if leg.mode != "WALK":
                continue
            # If enhance_walk + alternatives already scored this leg, skip re-annotation.
            if enhance_walk and leg.safety_matches:
                pass
            else:
                annotate_leg_from_danger_map(leg)
                annotate_leg_from_zones(leg)
                parts = [x for x in [leg.safety_score, leg.safety_zones_score] if x is not None]
                if parts:
                    leg.safety_score = round(sum(parts) / len(parts), 3)
            # Apply bias if requested (this still runs so totals include bias)
            if safety in ("prefer", "strict") and leg.safety_score is not None:
                if safety == "prefer":
                    factor = 1.0 + (1.0 - leg.safety_score) * 0.3
                else:
                    factor = 1.0 + (1.0 - leg.safety_score) * 0.6
                leg.duration_sec = int(leg.duration_sec * factor)

    # --- Option 3: Reject itineraries that cross unsafe zones (hard filter) ---
    if reject_walk_below is not None:
        survivors: List[Itinerary] = []
        for it in itineraries:
            walk_scores = [leg.safety_score for leg in it.legs if leg.mode == "WALK" and leg.safety_score is not None]
            # If no walk legs have scores, keep it (can't judge), otherwise require all walk legs to meet threshold
            if walk_scores and min(walk_scores) < float(reject_walk_below):
                continue
            survivors.append(it)
        itineraries = survivors
        if not itineraries:
            raise HTTPException(
                status_code=404,
                detail=f"All candidate itineraries were rejected by the safety filter (threshold={reject_walk_below}). Try lowering the threshold or using safety=prefer."
            )

    # recompute itinerary totals if any leg durations changed
    for it in itineraries:
        it.duration_sec = sum(leg.duration_sec for leg in it.legs)

    # If safety biasing is enabled, sort by (duration, -avg walk safety) so safer paths win ties
    if safety in ("prefer", "strict"):
        def avg_walk_safety(it: Itinerary) -> float:
            vals = [leg.safety_score for leg in it.legs if leg.mode == "WALK" and leg.safety_score is not None]
            return sum(vals)/len(vals) if vals else 0.5
        itineraries.sort(key=lambda it: (it.duration_sec, -avg_walk_safety(it)))

    return itineraries[:5]