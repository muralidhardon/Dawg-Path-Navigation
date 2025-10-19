#!/usr/bin/env python3
"""
Simple test script for the TransitAppBackEnd FastAPI server.
Usage:
    python test_backend.py --base http://127.0.0.1:8000

This script exercises:
 - POST /stops
 - GET /stops
 - POST /report
 - GET /eta?stop_id=...
 - GET /routes
 - GET /routes/{route_id}/stops

It prints a short report and exits with non-zero on failure.
"""

import argparse
import sys
import time
import requests
import json

DEFAULT_BASE = "http://127.0.0.1:8000"


def fatal(msg, code=1):
    print("ERROR:", msg)
    sys.exit(code)


def try_request(method, url, **kwargs):
    try:
        r = requests.request(method, url, timeout=5, **kwargs)
        return r
    except requests.exceptions.ConnectionError:
        fatal(f"Could not connect to server at {url}. Is the backend running? (Try: uvicorn TransitAppBackEnd:app --reload)")
    except Exception as e:
        fatal(f"Request to {url} failed: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=DEFAULT_BASE, help="Base URL for backend (default: %(default)s)")
    args = p.parse_args()
    base = args.base.rstrip("/")

    print(f"Testing backend at {base}")

    # 1) create a stop
    stop = {"id": 9999, "name": "Test Stop", "lat": 47.6062, "lng": -122.3321}
    url = f"{base}/stops"
    print("POST /stops -> creating test stop (id=9999)")
    r = try_request("post", url, json=stop)
    if r.status_code in (200, 201):
        print(" -> ok (status)", r.status_code)
    else:
        print(" -> warning: POST /stops returned status", r.status_code)
        # continue: maybe it already exists

    # 2) get stops and ensure we can find our stop
    print("GET /stops -> checking for the test stop")
    r = try_request("get", f"{base}/stops")
    if r.status_code != 200:
        fatal(f"GET /stops returned {r.status_code}")
    try:
        stops = r.json()
    except Exception:
        fatal("GET /stops did not return JSON")

    found = False
    for s in stops:
        if int(s.get("id")) == stop["id"]:
            found = True
            break
    if not found:
        fatal("Test stop not found in /stops response")
    print(" -> ok: test stop present")

    # 3) post a crowd report
    report = {"stop_id": stop["id"], "line_id": "TEST_LINE", "arrival_seconds": 300}
    print("POST /report -> adding a sample report")
    r = try_request("post", f"{base}/report", json=report)
    if r.status_code not in (200, 201):
        fatal(f"POST /report returned {r.status_code}")
    print(" -> ok: report accepted")

    # 4) query ETA for our stop
    print("GET /eta?stop_id=... -> fetching ETA")
    r = try_request("get", f"{base}/eta", params={"stop_id": stop["id"]})
    if r.status_code != 200:
        fatal(f"GET /eta returned {r.status_code}")
    try:
        eta = r.json()
    except Exception:
        fatal("GET /eta did not return JSON")

    if "eta_seconds" not in eta:
        fatal("/eta response missing eta_seconds")
    print(" -> ok: eta_seconds=", eta.get("eta_seconds"))

    # 5) GET /routes
    print("GET /routes -> checking route list (may be empty)")
    r = try_request("get", f"{base}/routes")
    if r.status_code != 200:
        fatal(f"GET /routes returned {r.status_code}")
    try:
        routes = r.json()
    except Exception:
        fatal("GET /routes did not return JSON")
    print(f" -> ok: routes returned (count={len(routes)})")

    # 6) GET /routes/FAKE/stops (should return [])
    print("GET /routes/FAKE/stops -> expecting empty list or []")
    r = try_request("get", f"{base}/routes/FAKE/stops")
    if r.status_code != 200:
        fatal(f"GET /routes/FAKE/stops returned {r.status_code}")
    try:
        rs = r.json()
    except Exception:
        fatal("GET /routes/FAKE/stops did not return JSON")
    print(f" -> ok: returned {type(rs).__name__} (len={len(rs) if hasattr(rs, '__len__') else 'n/a'})")

    print("\nAll tests passed.")
    sys.exit(0)


if __name__ == '__main__':
    main()
