"""Independent leakage audit of the frozen splits. Exit code 1 on any violation.

Re-derives every guarantee from the CSVs alone (does not trust make_splits.py):
  - split CSVs match the sha256 values frozen in SPLIT_MANIFEST.json
  - no request id, image sha1, address, geohash cell or group appears in two splits
  - no same-class pair across splits within BUFFER_M metres
  - no cross-split pair of images within NEAR_DUP_BITS of each other (dHash)
  - split files are exactly the rows of metadata.csv with that split value
  - with --images: every listed image exists and decodes

Usage: python3 scripts/verify_data.py [--images]
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
BUFFER_M = 50
NEAR_DUP_BITS = 6
PLACEHOLDER_ADDRESS = "not associated with a specific address"
SPLITS = ("train", "val", "test")
failures = []


def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def popcount64(x):
    x = x - ((x >> 1) & 0x5555555555555555)
    x = (x & 0x3333333333333333) + ((x >> 2) & 0x3333333333333333)
    x = (x + (x >> 4)) & 0x0F0F0F0F0F0F0F0F
    return (x * 0x0101010101010101) >> 56


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true", help="also check image files on disk")
    args = ap.parse_args()

    manifest = json.loads((DATA / "SPLIT_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        actual = hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        check(actual == digest, f"{name} matches frozen sha256")

    meta = list(csv.DictReader(open(DATA / "metadata.csv")))
    split_rows = {s: list(csv.DictReader(open(DATA / f"{s}.csv"))) for s in SPLITS}
    for s in SPLITS:
        ids = {r["service_request_id"] for r in split_rows[s]}
        expect = {r["service_request_id"] for r in meta if r["split"] == s}
        check(ids == expect, f"{s}.csv == metadata rows with split={s} ({len(ids)})")

    for key in ("service_request_id", "sha1", "geohash", "group"):
        seen = {}
        for r in meta:
            seen.setdefault(r[key], set()).add(r["split"])
        bad = sum(1 for v in seen.values() if len(v) > 1)
        check(bad == 0, f"no {key} shared across splits ({bad} shared)")
    seen = {}
    for r in meta:
        if r["address"].lower() != PLACEHOLDER_ADDRESS:
            seen.setdefault(r["address"].lower(), set()).add(r["split"])
    bad = sum(1 for v in seen.values() if len(v) > 1)
    check(bad == 0, f"no address shared across splits ({bad} shared)")

    # same-class spatial buffer, every pair of splits
    close = 0
    for a, b in (("train", "test"), ("val", "test"), ("train", "val")):
        for label in {r["label"] for r in meta}:
            A = np.radians([[float(r["lat"]), float(r["long"])] for r in split_rows[a] if r["label"] == label])
            B = np.radians([[float(r["lat"]), float(r["long"])] for r in split_rows[b] if r["label"] == label])
            for i in range(0, len(B), 1024):
                bb = B[i:i + 1024]
                d = 6_371_000 * np.hypot(A[:, None, 0] - bb[None, :, 0],
                                         (A[:, None, 1] - bb[None, :, 1]) * np.cos(A[:, None, 0]))
                close += int((d <= BUFFER_M).sum())
    check(close == 0, f"no same-class cross-split pair within {BUFFER_M} m ({close} pairs)")

    near = 0
    hashes = {s: np.array([int(r["dhash"], 16) for r in split_rows[s]], dtype=np.uint64) for s in SPLITS}
    for a, b in (("train", "test"), ("val", "test"), ("train", "val")):
        for i in range(0, len(hashes[b]), 512):
            d = popcount64(hashes[a][:, None] ^ hashes[b][None, i:i + 512])
            near += int((d <= NEAR_DUP_BITS).sum())
    check(near == 0, f"no cross-split near-duplicate images, dHash <= {NEAR_DUP_BITS} bits ({near} pairs)")

    if args.images:
        from PIL import Image
        missing = bad_img = 0
        for r in meta:
            p = DATA / r["path"]
            if not p.exists():
                missing += 1
                continue
            try:
                Image.open(p).verify()
            except Exception:
                bad_img += 1
        check(missing == 0 and bad_img == 0, f"all {len(meta)} images present and decodable "
              f"({missing} missing, {bad_img} corrupt)")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
