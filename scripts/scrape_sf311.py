"""Scrape a class-balanced SF 311 photo dataset from DataSF (dataset vw6y-z8j6).

Only Cloudinary-hosted photos are used: they are direct JPEG links. The other
host (Verint web forms) returns an HTML page, not an image.

Usage:
  python3 scrape_sf311.py --per-class 20 --out pilot     # pilot
  python3 scrape_sf311.py --per-class 1800 --out sf311   # full run (~30k)
"""
import argparse
import csv
import hashlib
import io
import json
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from PIL import Image

API = "https://data.sf.gov/resource/vw6y-z8j6.json"
START = date(2024, 10, 1)
END = date(2026, 10, 1)
MAX_SIDE = 768          # images are downscaled; plenty for 224-512px training
MAX_PER_ADDRESS = 3     # repeat reporters file the same spot over and over
TEST_PCT = 15           # held-out share, split by address so a spot never leaks across splits
OVERSAMPLE = 1.6        # candidates fetched per needed image (dead links, dupes, address cap)

# label -> SoQL condition. Classes are chosen to be visually identifiable from a photo.
CLASSES = {
    "garbage_debris":     "service_name='Street and Sidewalk Cleaning' AND service_subtype='garbage_and_debris'",
    "graffiti":           "service_name in ('Graffiti Public','Graffiti Private')",
    "encampment":         "service_name='Encampment'",
    "parked_on_sidewalk": "service_name='Parking Enforcement' AND service_subtype='parking_on_sidewalk'",
    "blocking_driveway":  "service_name='Parking Enforcement' AND service_subtype in ('blocking_driveway_cite_only','blocking_driveway_cite_tow')",
    "abandoned_vehicle":  "service_name='Parking Enforcement' AND service_subtype='abandoned_vehicle'",
    "blocked_sidewalk":   "service_name='Blocked Street and Sidewalk'",
    "sidewalk_defect":    "service_name='Sidewalk and Curb' AND service_subtype='sidewalk_defect'",
    "pavement_defect":    "service_name='Sidewalk and Curb' AND service_subtype='pavement_defect'",
    "curb_ramp_defect":   "service_name='Sidewalk and Curb' AND service_subtype='curb_or_curb_ramp_defect'",
    "sewer_vent_cover":   "service_name='Sidewalk and Curb' AND service_subtype in ('missing_side_sewer_vent_cover','damaged_side_sewer_vent_cover')",
    "tree_issue":         "service_name='Tree Maintenance'",
    "illegal_posting":    "service_name='Illegal Postings'",
    "litter_receptacle":  "service_name='Litter Receptacle Maintenance'",
    "streetlight":        "service_name='Streetlights'",
    "sewer_flooding":     "service_name='Sewer'",
    "traffic_sign":       "service_name in ('MTA Parking Traffic Signs Normal Priority','MTA Parking Traffic Signs High Priority')",
}

FIELDS = ["service_request_id", "requested_datetime", "service_name", "service_subtype",
          "service_details", "agency_responsible", "address", "lat", "long",
          "analysis_neighborhood", "supervisor_district", "source", "media_url"]


def get_json(params, retries=4):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


CHUNK = 50  # rows per random-offset page


def fetch_candidates(label, cond, per_class):
    """Pull small pages at random offsets across the whole date range, so samples
    are spread over time instead of clustering on the first rows of a window."""
    where = (f"({cond}) AND media_url.url like '%cloudinary%' "
             f"AND requested_datetime >= '{START}' AND requested_datetime < '{END}'")
    total = int(get_json({"$select": "count(*)", "$where": where})[0]["count"])
    n_chunks = min(total // CHUNK + 1, int(per_class * OVERSAMPLE / CHUNK) + 1)
    rng = random.Random(label)
    slots = rng.sample(range(total // CHUNK + 1), n_chunks)
    page = lambda i: get_json({"$select": ",".join(FIELDS), "$where": where,
                               "$order": "requested_datetime,service_request_id",
                               "$limit": CHUNK, "$offset": i * CHUNK})
    with ThreadPoolExecutor(8) as ex:
        rows = [r for chunk in ex.map(page, slots) for r in chunk]
    rng.shuffle(rows)
    return rows


def split_for(address):
    h = int(hashlib.sha1((address or "").lower().encode()).hexdigest(), 16)
    return "test" if h % 100 < TEST_PCT else "train"


def download(row, out_dir, label):
    """Fetch, validate and downscale one photo. Returns (row, info|None, status)."""
    rel = Path("images") / label / f"{row['service_request_id']}.jpg"
    dest = out_dir / rel
    try:
        if dest.exists():  # resume: reuse a photo saved by an earlier run
            data = dest.read_bytes()
            img = Image.open(io.BytesIO(data))
        else:
            req = urllib.request.Request(row["media_url"]["url"],
                                         headers={"User-Agent": "calhacks-sf311-research"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if not r.headers.get("Content-Type", "").startswith("image/"):
                    return row, None, "not_image"
                data = r.read()
            img = Image.open(io.BytesIO(data))
            img.load()
            if min(img.size) < 128:
                return row, None, "too_small"
            img = img.convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=90)
            dest.write_bytes(buf.getvalue())
        return row, {"path": str(rel), "sha1": hashlib.sha1(data).hexdigest(),
                     "width": img.size[0], "height": img.size[1]}, "ok"
    except Exception as e:
        return row, None, type(e).__name__


def scrape_class(label, cond, per_class, out_dir, workers, seen_sha, stats):
    (out_dir / "images" / label).mkdir(parents=True, exist_ok=True)
    cands = fetch_candidates(label, cond, per_class)
    per_addr = Counter()
    queue = []
    for r in cands:
        addr = (r.get("address") or "").lower()
        if per_addr[addr] >= MAX_PER_ADDRESS:
            stats["address_cap"] += 1
            continue
        per_addr[addr] += 1
        queue.append(r)

    kept = []
    it = iter(queue)
    with ThreadPoolExecutor(workers) as ex:
        # keep ~workers jobs in flight so we stop soon after the quota is met
        pending = {ex.submit(download, r, out_dir, label) for r, _ in zip(it, range(workers))}
        while pending:
            done = next(as_completed(pending))
            pending.discard(done)
            row, info, status = done.result()
            if info and info["sha1"] in seen_sha:
                status, info = "duplicate", None
                (out_dir / "images" / label / f"{row['service_request_id']}.jpg").unlink(missing_ok=True)
            if info and len(kept) >= per_class:
                (out_dir / info["path"]).unlink(missing_ok=True)
                status, info = "over_quota", None
            stats[status] += 1
            if info:
                seen_sha.add(info["sha1"])
                kept.append((row, info))
            if len(kept) < per_class:
                nxt = next(it, None)
                if nxt is not None:
                    pending.add(ex.submit(download, nxt, out_dir, label))
    return kept, len(cands)


def write_outputs(out_dir, all_kept):
    cols = ["path", "label", "split", "service_request_id", "requested_datetime",
            "service_name", "service_subtype", "service_details", "agency_responsible",
            "address", "lat", "long", "analysis_neighborhood", "supervisor_district",
            "source", "width", "height", "sha1", "media_url"]
    rows = []
    for label, row, info in all_kept:
        rows.append({**{k: row.get(k, "") for k in cols}, **info, "label": label,
                     "split": split_for(row.get("address")), "media_url": row["media_url"]["url"]})
    rows.sort(key=lambda r: (r["label"], r["service_request_id"]))
    for name, subset in [("metadata.csv", rows),
                         ("train.csv", [r for r in rows if r["split"] == "train"]),
                         ("test.csv", [r for r in rows if r["split"] == "test"])]:
        with open(out_dir / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(subset)
    # label -> index, plus which agencies actually handled each class (for routing in the app)
    agencies = defaultdict(Counter)
    for r in rows:
        agencies[r["label"]][r["agency_responsible"]] += 1
    labels = {
        "classes": sorted(CLASSES),
        "soql_filter": CLASSES,
        "top_agencies": {l: agencies[l].most_common(5) for l in sorted(CLASSES)},
    }
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only", nargs="*", help="limit to these labels (debugging)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_sha, all_kept, report = set(), [], {}
    t0 = time.time()
    for label, cond in CLASSES.items():
        if args.only and label not in args.only:
            continue
        stats = Counter()
        kept, n_cands = scrape_class(label, cond, args.per_class, out_dir, args.workers, seen_sha, stats)
        all_kept += [(label, row, info) for row, info in kept]
        report[label] = {"kept": len(kept), "candidates": n_cands, **stats}
        short = "" if len(kept) >= args.per_class else f"  SHORT by {args.per_class - len(kept)}"
        print(f"{label:20s} kept={len(kept):5d} cands={n_cands:5d} {dict(stats)} "
              f"[{time.time() - t0:.0f}s]{short}", flush=True)
    rows = write_outputs(out_dir, all_kept)
    (out_dir / "scrape_report.json").write_text(json.dumps(report, indent=2))
    split = Counter(r["split"] for r in rows)
    print(f"TOTAL {len(rows)} images  train={split['train']} test={split['test']}  "
          f"[{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    sys.exit(main())
