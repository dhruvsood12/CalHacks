"""Rebuild dataset images from the manifest (images are not in git).

Downloads each photo from its original media_url, checks the sha1 of the original
bytes against the manifest, and writes the same downscaled JPEG the scraper wrote
(max side 768, quality 90) to data/<path>.

Usage:
  python3 scripts/fetch_images.py --ids reports/claude_baseline_ids.csv
  python3 scripts/fetch_images.py --split val --per-class 20
  python3 scripts/fetch_images.py --split train            # whole split (~20k, ~15 min)
"""
import argparse
import csv
import hashlib
import io
import random
import sys
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_SIDE = 768


def fetch(row):
    dest = DATA / row["path"]
    if dest.exists():
        return "exists"
    try:
        req = urllib.request.Request(row["media_url"], headers={"User-Agent": "calhacks-sf311-research"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if hashlib.sha1(data).hexdigest() != row["sha1"]:
            return "sha1_mismatch"
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        dest.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        dest.write_bytes(buf.getvalue())
        return "ok"
    except Exception as e:
        return type(e).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="CSV with a service_request_id column")
    ap.add_argument("--split", choices=["train", "val", "test"])
    ap.add_argument("--per-class", type=int)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    meta = {r["service_request_id"]: r for r in csv.DictReader(open(DATA / "metadata.csv"))}
    if args.ids:
        rows = [meta[r["service_request_id"]] for r in csv.DictReader(open(args.ids))]
    elif args.split:
        rows = [r for r in meta.values() if r["split"] == args.split]
    else:
        ap.error("pass --ids or --split")
    if args.per_class:
        by = defaultdict(list)
        for r in rows:
            by[r["label"]].append(r)
        rng = random.Random(13)
        rows = [r for l in sorted(by) for r in rng.sample(by[l], min(args.per_class, len(by[l])))]

    with ThreadPoolExecutor(args.workers) as ex:
        status = Counter(ex.map(fetch, rows))
    print(dict(status))
    return 0 if set(status) <= {"ok", "exists"} else 1


if __name__ == "__main__":
    sys.exit(main())
