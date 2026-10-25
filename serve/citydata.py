"""B3b: city context behind GET /context?label=&lat=&lng= (A's serve/app.py calls `get_context`).

    from serve.citydata import get_context
    body = get_context("pavement_defect", 37.8012, -122.4477)   # contracts/context.response.schema.json

- **Already reported?** one live SoQL query to DataSF (vw6y-z8j6): the class's `sf311_filter`,
  within_circle(point, lat, lng, 75 m), status Open, filed in the last 30 days. distance_m is
  computed here; the 5 newest are returned. 5 s timeout; on any failure nearby_open = [].
- **Fix time:** median and p75 days-to-close per class over the last 12 months citywide, plus a
  per-supervisor-district version where n >= 30. Computed on first use and cached in
  serve/cache/fix_times.json (gitignored). Falls back to docs/evidence/city_context_stats.json
  if DataSF is unreachable, so the flow never blocks.
- **Address:** the nearest city-record address within 40 m, any category.
- Read-only. Never calls any SF 311 write endpoint.

Warm the cache at startup:  python -m serve.citydata --warm
Try one point:              python -m serve.citydata --label pavement_defect --lat 37.8012 --lng -122.4477
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
API = "https://data.sf.gov/resource/vw6y-z8j6.json"
CATEGORIES_PATH = ROOT / "contracts" / "categories.json"
EVIDENCE_PATH = ROOT / "docs" / "evidence" / "city_context_stats.json"
CACHE_PATH = Path(__file__).resolve().parent / "cache" / "fix_times.json"

RADIUS_M = 75
NEARBY_DAYS = 30
NEARBY_MAX = 5
ADDRESS_RADIUS_M = 40
FIX_WINDOW_DAYS = 365
FIX_PAGE = 50000
DISTRICT_MIN_N = 30
CACHE_TTL_S = 24 * 3600
TIMEOUT_LIVE_S = 5
TIMEOUT_STATS_S = 120
NO_ADDRESS = "Not associated with a specific address"

CATEGORIES = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))["classes"]
FILTER = {c["label"]: c["sf311_filter"] for c in CATEGORIES}
_lock = threading.Lock()


# ----------------------------------------------------------------------------
# SoQL
# ----------------------------------------------------------------------------
def _ssl_context():
    """Default TLS context, with certifi's CA bundle when the system store is missing one
    (stock Windows Python; the Linux GPU box is fine either way)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


def _soql(params: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    """GET one page from DataSF. Separated so tests can monkeypatch it."""
    headers = {"User-Agent": "calhacks-snap311-context"}
    token = os.environ.get("SODA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        return json.load(r)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19])
    except ValueError:
        return None


def _now() -> datetime:
    # DataSF timestamps are local (Pacific) naive strings; compare in the same frame.
    return datetime.now()


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _check_label(label: str) -> None:
    if label not in FILTER:
        raise ValueError(f"unknown label {label!r}; see contracts/categories.json")


# ----------------------------------------------------------------------------
# already reported?
# ----------------------------------------------------------------------------
def nearby_open(label: str, lat: float, lng: float, radius_m: int = RADIUS_M, days: int = NEARBY_DAYS,
                timeout: float = TIMEOUT_LIVE_S) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(contract items newest-first, max 5; raw rows). Raises on network failure (caller catches)."""
    _check_label(label)
    since = _iso(_now() - timedelta(days=days))
    where = (f"({FILTER[label]}) AND within_circle(point, {lat:.6f}, {lng:.6f}, {radius_m}) "
             f"AND status_description='Open' AND requested_datetime >= '{since}'")
    rows = _soql({"$select": "service_request_id,requested_datetime,status_description,address,lat,long,"
                             "supervisor_district,data_as_of",
                  "$where": where, "$order": "requested_datetime DESC", "$limit": 50}, timeout)
    now = _now()
    items = []
    for r in rows:
        try:
            rlat, rlng = float(r["lat"]), float(r["long"])
        except (KeyError, TypeError, ValueError):
            continue
        ts = _parse_ts(r.get("requested_datetime"))
        if ts is None:
            continue
        d = haversine_m(lat, lng, rlat, rlng)
        if d > radius_m + 1:  # DataSF already filtered; guard against point/lat-long drift
            continue
        addr = r.get("address")
        items.append({
            "service_request_id": str(r["service_request_id"]),
            "distance_m": round(d, 1),
            "requested_at": _iso(ts),
            "days_open": round(max((now - ts).total_seconds() / 86400, 0.0), 2),
            "status": str(r.get("status_description") or "Open"),
            "address": None if not addr or addr == NO_ADDRESS else addr,
        })
    items.sort(key=lambda x: x["requested_at"], reverse=True)
    return items[:NEARBY_MAX], rows


def nearest_address(lat: float, lng: float, radius_m: int = ADDRESS_RADIUS_M,
                    timeout: float = TIMEOUT_LIVE_S) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """(address, supervisor_district, raw rows) of the nearest city record with a street address."""
    where = (f"within_circle(point, {lat:.6f}, {lng:.6f}, {radius_m}) AND address IS NOT NULL "
             f"AND address != '{NO_ADDRESS}'")
    rows = _soql({"$select": "address,lat,long,supervisor_district,data_as_of", "$where": where,
                  "$order": "requested_datetime DESC", "$limit": 25}, timeout)
    best, best_d, district = None, float("inf"), None
    for r in rows:
        try:
            d = haversine_m(lat, lng, float(r["lat"]), float(r["long"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d < best_d and r.get("address"):
            best, best_d, district = r["address"], d, r.get("supervisor_district")
    return best, (str(int(float(district))) if district not in (None, "") else None), rows


# ----------------------------------------------------------------------------
# fix times
# ----------------------------------------------------------------------------
def _percentiles(days: list[float]) -> tuple[float, float]:
    s = sorted(days)
    n = len(s)

    def q(p: float) -> float:
        if n == 1:
            return s[0]
        k = (n - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return round(q(0.5), 2), round(q(0.75), 2)


def compute_fix_times(label: str, timeout: float = TIMEOUT_STATS_S) -> dict[str, Any]:
    """Days to close for cases of this class filed in the last 12 months (one page of up to
    50k most-recent closed cases), citywide and per supervisor district (n >= 30)."""
    _check_label(label)
    since = _iso(_now() - timedelta(days=FIX_WINDOW_DAYS))
    rows = _soql({"$select": "requested_datetime,closed_date,supervisor_district",
                  "$where": f"({FILTER[label]}) AND requested_datetime >= '{since}' AND closed_date IS NOT NULL",
                  "$order": "requested_datetime DESC", "$limit": FIX_PAGE}, timeout)
    city: list[float] = []
    by_d: dict[str, list[float]] = {}
    for r in rows:
        a, b = _parse_ts(r.get("requested_datetime")), _parse_ts(r.get("closed_date"))
        if a is None or b is None or b < a:
            continue
        d = (b - a).total_seconds() / 86400
        city.append(d)
        dist = r.get("supervisor_district")
        if dist not in (None, ""):
            by_d.setdefault(str(int(float(dist))), []).append(d)
    capped = len(rows) >= FIX_PAGE
    scope = "citywide, last 12 months" + (f" (most recent {FIX_PAGE:,} cases)" if capped else "")
    out: dict[str, Any] = {"computed": _iso(_now()), "window_start": since, "capped": capped}
    if city:
        med, p75 = _percentiles(city)
        out["citywide"] = {"median_days": med, "p75_days": p75, "n": len(city), "scope": scope}
    out["districts"] = {}
    for dist, v in by_d.items():
        if len(v) >= DISTRICT_MIN_N:
            med, p75 = _percentiles(v)
            out["districts"][dist] = {"median_days": med, "p75_days": p75, "n": len(v),
                                      "scope": f"District {dist}, last 12 months"}
    return out


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass


def _evidence_fallback(label: str) -> dict[str, Any] | None:
    try:
        ev = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))["per_class"][label]
    except (OSError, ValueError, KeyError):
        return None
    if ev.get("median_days_to_close") is None:
        return None
    return {"median_days": float(ev["median_days_to_close"]), "p75_days": float(ev["p75_days_to_close"]),
            "n": int(ev["new_reports"]), "scope": "citywide, 2025-06 sample (cached evidence)"}


def fix_time(label: str, district: str | None = None, allow_network: bool = True) -> dict[str, Any] | None:
    """Contract `fix_time` object for the label (district version when available), or None."""
    _check_label(label)
    with _lock:
        cache = _load_cache()
    entry = cache.get(label)
    fresh = entry and (time.time() - _parse_ts(entry["computed"]).timestamp() < CACHE_TTL_S if _parse_ts(entry.get("computed")) else False)
    if not fresh and allow_network:
        try:
            entry = compute_fix_times(label)
            with _lock:
                cache = _load_cache()
                cache[label] = entry
                _save_cache(cache)
        except Exception:
            entry = entry or None  # keep a stale entry over nothing
    if not entry:
        return _evidence_fallback(label)
    if district and district in entry.get("districts", {}):
        return dict(entry["districts"][district])
    return dict(entry["citywide"]) if entry.get("citywide") else _evidence_fallback(label)


def warm_cache(labels: list[str] | None = None, workers: int = 4) -> dict[str, Any]:
    labels = labels or list(FILTER)
    with ThreadPoolExecutor(workers) as ex:
        results = dict(zip(labels, ex.map(lambda l: compute_fix_times(l), labels)))
    with _lock:
        cache = _load_cache()
        cache.update(results)
        _save_cache(cache)
    return results


# ----------------------------------------------------------------------------
# the endpoint body
# ----------------------------------------------------------------------------
def get_context(label: str, lat: float, lng: float) -> dict[str, Any]:
    """Body of GET /context. Never raises for network trouble: nearby_open=[] / fix_time from cache or evidence."""
    _check_label(label)
    lat, lng = float(lat), float(lng)
    rows_seen: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    address, district = None, None

    def _nearby():
        nonlocal nearby
        try:
            nearby, raw = nearby_open(label, lat, lng)
            rows_seen.extend(raw)
        except Exception:
            nearby = []

    def _addr():
        nonlocal address, district
        try:
            address, district, raw = nearest_address(lat, lng)
            rows_seen.extend(raw)
        except Exception:
            address, district = None, None

    t1, t2 = threading.Thread(target=_nearby), threading.Thread(target=_addr)
    t1.start(); t2.start(); t1.join(TIMEOUT_LIVE_S + 1); t2.join(TIMEOUT_LIVE_S + 1)
    ft = fix_time(label, district)
    data_as_of = max((r.get("data_as_of") or "" for r in rows_seen), default="") or _iso(_now())
    return {
        "label": label,
        "address": address,
        "nearby_open": nearby,
        "fix_time": ft,
        "data_as_of": data_as_of[:19],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warm", action="store_true", help="precompute fix times for all 17 classes")
    ap.add_argument("--label")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    args = ap.parse_args()
    if args.warm:
        t0 = time.time()
        res = warm_cache()
        for l, v in res.items():
            c = v.get("citywide", {})
            print(f"{l:20s} n={c.get('n', 0):6d} median={c.get('median_days')}d p75={c.get('p75_days')}d "
                  f"districts(n>=30)={len(v.get('districts', {}))}")
        print(f"cached to {CACHE_PATH} in {time.time() - t0:.0f}s")
    if args.label:
        t0 = time.time()
        body = get_context(args.label, args.lat, args.lng)
        print(json.dumps(body, indent=2))
        print(f"({(time.time() - t0) * 1000:.0f} ms)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
