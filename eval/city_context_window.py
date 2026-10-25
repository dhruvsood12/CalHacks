"""B3b evidence: re-run scripts/city_context_stats.py's measurement on a SECOND window to show
the "already reported nearby" rate is stable, not a quirk of the June 2025 fortnight.

  python eval/city_context_window.py [--start 2025-11-01 --end 2025-11-15] [--lookback-days 14] [--radius-m 50]
  -> reports/city_context_stats_<start>.json   (same shape as docs/evidence/city_context_stats.json)

Reuses the shared script's functions unchanged (scripts/ is a shared lane); only the window
constants are overridden here. Read-only DataSF queries; no 311 write endpoint is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # stock Windows Python lacks data.sf.gov's GlobalSign root; Linux is fine either way
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

import city_context_stats as S  # noqa: E402  (scripts/city_context_stats.py)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2025-11-01")
    ap.add_argument("--end", default="2025-11-15")
    ap.add_argument("--lookback-days", type=int, default=14)
    ap.add_argument("--radius-m", type=int, default=50)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    S.WINDOW_START, S.WINDOW_END = args.start, args.end
    S.LOOKBACK_START = (datetime.fromisoformat(args.start) - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    S.LOOKBACK_DAYS, S.RADIUS_M = args.lookback_days, args.radius_m

    with ThreadPoolExecutor(args.workers) as ex:
        out = dict(ex.map(S.analyse, S.CLASSES.items()))
    tot_new = sum(v["new_reports"] for v in out.values())
    tot_dup = sum(v["already_open_nearby"] for v in out.values())
    result = {
        "window": [args.start, args.end], "lookback_days": args.lookback_days, "radius_m": args.radius_m,
        "source": "DataSF 311 Cases vw6y-z8j6, all sources",
        "method": "scripts/city_context_stats.py (unchanged), window overridden by eval/city_context_window.py",
        "computed": datetime.now().isoformat(timespec="seconds"),
        "overall": {"new_reports": tot_new, "already_open_nearby": tot_dup,
                    "already_open_nearby_pct": round(100 * tot_dup / max(tot_new, 1), 1)},
        "per_class": out,
    }
    try:
        first = json.loads((ROOT / "docs" / "evidence" / "city_context_stats.json").read_text(encoding="utf-8"))
        result["comparison_with_first_window"] = {
            "first_window": first["window"], "first_pct": first["overall"]["already_open_nearby_pct"],
            "this_pct": result["overall"]["already_open_nearby_pct"],
            "per_class_pct": {k: {"first": first["per_class"][k]["already_open_nearby_pct"], "this": v["already_open_nearby_pct"]}
                              for k, v in out.items() if k in first["per_class"]},
        }
    except (OSError, KeyError, ValueError):
        pass
    path = ROOT / "reports" / f"city_context_stats_{args.start}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["overall"]), "->", path.relative_to(ROOT))
    for l, v in sorted(out.items(), key=lambda x: -x[1]["already_open_nearby_pct"]):
        print(f"{l:20s} new={v['new_reports']:6d} dup_open_{args.radius_m}m={v['already_open_nearby_pct']:5.1f}% "
              f"median_close={v['median_days_to_close']}d p75={v['p75_days_to_close']}d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
