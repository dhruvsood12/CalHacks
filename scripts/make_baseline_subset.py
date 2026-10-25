"""Pre-register the fixed image subsets used to evaluate Claude zero-shot.

Written once, before any model or prompt exists, so neither can be tuned to them:
  reports/claude_prompt_dev_ids.csv  20/class from VAL  - prompt development only
  reports/claude_baseline_ids.csv    60/class from TEST - the one frozen baseline run

Run: python3 scripts/make_baseline_subset.py
"""
import csv
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 13


def sample(split_csv, per_class, out_csv):
    by = defaultdict(list)
    for r in csv.DictReader(open(ROOT / "data" / split_csv)):
        by[r["label"]].append(r)
    rng = random.Random(SEED)
    rows = []
    for label in sorted(by):
        pool = sorted(by[label], key=lambda r: r["service_request_id"])
        rows += rng.sample(pool, per_class)
    with open(ROOT / "reports" / out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["service_request_id", "label", "path", "split"])
        w.writeheader()
        w.writerows({k: r[k] for k in w.fieldnames} for r in rows)
    print(out_csv, len(rows))


if __name__ == "__main__":
    sample("val.csv", 20, "claude_prompt_dev_ids.csv")
    sample("test.csv", 60, "claude_baseline_ids.csv")
