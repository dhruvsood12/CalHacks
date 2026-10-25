"""Measure, from DataSF, how often a new report duplicates an already-open one nearby
and how long each class takes to close. Evidence for the "already reported?" and
"expected fix time" features. Output: docs/evidence/city_context_stats.json

Window: reports filed 2025-06-15..2025-06-29 (all sources), looking back 14 days
for an earlier same-class report within RADIUS_M that was still open at filing time.

Run: python3 scripts/city_context_stats.py
"""
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scrape_sf311 import API, CLASSES  # noqa: E402

LOOKBACK_START, WINDOW_START, WINDOW_END = "2025-06-01", "2025-06-15", "2025-06-29"
RADIUS_M = 50
LOOKBACK_DAYS = 14


def fetch(cond):
    rows, offset = [], 0
    where = f"({cond}) AND requested_datetime >= '{LOOKBACK_START}' AND requested_datetime < '{WINDOW_END}' AND lat IS NOT NULL"
    while True:
        q = urllib.parse.urlencode({"$select": "service_request_id,requested_datetime,closed_date,lat,long",
                                    "$where": where, "$order": "requested_datetime", "$limit": 50000, "$offset": offset})
        with urllib.request.urlopen(f"{API}?{q}", timeout=180) as r:
            page = json.load(r)
        rows += page
        if len(page) < 50000:
            return rows
        offset += 50000


def ts(s):
    return datetime.fromisoformat(s[:19]) if s else None


def analyse(item):
    label, cond = item
    rows = [r for r in fetch(cond) if float(r["lat"]) > 37]
    t = np.array([ts(r["requested_datetime"]).timestamp() for r in rows])
    closed = np.array([ts(r["closed_date"]).timestamp() if r.get("closed_date") else np.inf for r in rows])
    ll = np.radians([[float(r["lat"]), float(r["long"])] for r in rows])
    new = np.nonzero(t >= ts(WINDOW_START).timestamp())[0]
    dup = 0
    for i in new:
        prev = np.nonzero((t < t[i]) & (t >= t[i] - LOOKBACK_DAYS * 86400) & (closed > t[i]))[0]
        if len(prev):
            d = 6_371_000 * np.hypot(ll[prev, 0] - ll[i, 0], (ll[prev, 1] - ll[i, 1]) * np.cos(ll[i, 0]))
            dup += bool((d <= RADIUS_M).any())
    days = (closed[new] - t[new]) / 86400
    done = days[np.isfinite(days)]
    return label, {
        "new_reports": int(len(new)),
        "already_open_nearby": int(dup),
        "already_open_nearby_pct": round(100 * dup / max(len(new), 1), 1),
        "closed_pct": round(100 * len(done) / max(len(new), 1), 1),
        "median_days_to_close": round(float(np.median(done)), 2) if len(done) else None,
        "p75_days_to_close": round(float(np.percentile(done, 75)), 2) if len(done) else None,
    }


def main():
    with ThreadPoolExecutor(6) as ex:
        out = dict(ex.map(analyse, CLASSES.items()))
    tot_new = sum(v["new_reports"] for v in out.values())
    tot_dup = sum(v["already_open_nearby"] for v in out.values())
    result = {"window": [WINDOW_START, WINDOW_END], "lookback_days": LOOKBACK_DAYS, "radius_m": RADIUS_M,
              "source": "DataSF 311 Cases vw6y-z8j6, all sources", "computed": datetime.now().isoformat(timespec="seconds"),
              "overall": {"new_reports": tot_new, "already_open_nearby": tot_dup,
                          "already_open_nearby_pct": round(100 * tot_dup / tot_new, 1)},
              "per_class": out}
    path = ROOT / "docs" / "evidence" / "city_context_stats.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["overall"]))
    for l, v in sorted(out.items(), key=lambda x: -x[1]["already_open_nearby_pct"]):
        print(f"{l:20s} new={v['new_reports']:6d} dup_open_50m={v['already_open_nearby_pct']:5.1f}% "
              f"median_close={v['median_days_to_close']}d p75={v['p75_days_to_close']}d closed={v['closed_pct']}%")


if __name__ == "__main__":
    main()
