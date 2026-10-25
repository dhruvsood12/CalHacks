"""Freeze leakage-safe train/val/test splits for the SF 311 photo dataset.

Leakage controls, in order:
  1. Spatial grouping: every photo is assigned to a geohash-7 cell (~150 x 150 m, about one city block).
     A cell lives in exactly one split, so the same block, encampment, tagged wall
     or repeat reporter never appears on both sides.
  2. Stratified group folds: cells are dealt into 7 folds while balancing classes
     (fold 0 = test, fold 1 = val, folds 2-6 = train), ~14% / ~14% / ~72%.
  3. Near-duplicate purge: a 64-bit difference hash (dHash) is computed for every
     image; any train/val image within Hamming distance <= NEAR_DUP_BITS of a test
     image (or train image near a val image) is dropped from the non-test side.
     Exact duplicates were already removed by sha1 at scrape time.
  4. Spatial buffer: a train/val photo of the SAME class within BUFFER_M metres of a
     test photo (or a train photo near a val photo) is dropped. This closes the gap
     where one object sits on the edge between two neighbouring blocks.
  5. A manifest with sha256 of each split CSV is written; CI fails if they change.

Input:  data/scrape_manifest.csv (raw scrape output, never modified)
Output: data/metadata.csv, train.csv, val.csv, test.csv, SPLIT_MANIFEST.json
Run:    python3 scripts/make_splits.py   (deterministic; safe to re-run)
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.model_selection import StratifiedGroupKFold

DATA = Path(__file__).resolve().parent.parent / "data"
SEED = 13
GEOHASH_PRECISION = 7
N_FOLDS = 7
NEAR_DUP_BITS = 6
PLACEHOLDER_ADDRESS = "not associated with a specific address"
BUFFER_M = 50
_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat, lon, precision):
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    bits, ch, even, out = 0, 0, True, []
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch = (ch << 1) | 1
            rng[0] = mid
        else:
            ch <<= 1
            rng[1] = mid
        even = not even
        bits += 1
        if bits == 5:
            out.append(_B32[ch])
            bits, ch = 0, 0
    return "".join(out)


def dhash(path):
    im = Image.open(path).convert("L").resize((9, 8), Image.BILINEAR)
    a = np.asarray(im, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def popcount64(x):
    x = x - ((x >> 1) & 0x5555555555555555)
    x = (x & 0x3333333333333333) + ((x >> 2) & 0x3333333333333333)
    x = (x + (x >> 4)) & 0x0F0F0F0F0F0F0F0F
    return (x * 0x0101010101010101) >> 56


def near_dups(query, ref):
    """Indices into `query` whose hash is within NEAR_DUP_BITS of any hash in `ref`."""
    q = np.array(query, dtype=np.uint64)
    hits = set()
    for start in range(0, len(ref), 512):
        r = np.array(ref[start:start + 512], dtype=np.uint64)
        d = popcount64(q[:, None] ^ r[None, :])
        hits.update(np.nonzero((d <= NEAR_DUP_BITS).any(axis=1))[0].tolist())
    return hits


def close_pairs(query, ref, metres):
    """Indices into `query` rows within `metres` of any `ref` row of the same label."""
    hits = set()
    for label in {r["label"] for r in query}:
        qi = [i for i, r in enumerate(query) if r["label"] == label]
        rr = [r for r in ref if r["label"] == label]
        if not qi or not rr:
            continue
        q = np.radians([[float(query[i]["lat"]), float(query[i]["long"])] for i in qi])
        f = np.radians([[float(r["lat"]), float(r["long"])] for r in rr])
        for start in range(0, len(f), 1024):
            b = f[start:start + 1024]
            dlat = q[:, None, 0] - b[None, :, 0]
            dlon = (q[:, None, 1] - b[None, :, 1]) * np.cos(q[:, None, 0])
            d = 6_371_000 * np.sqrt(dlat ** 2 + dlon ** 2)
            hits.update(qi[j] for j in np.nonzero((d <= metres).any(axis=1))[0])
    return hits


def main():
    rows = list(csv.DictReader(open(DATA / "scrape_manifest.csv")))
    for r in rows:
        r["geohash"] = geohash(float(r["lat"]), float(r["long"]), GEOHASH_PRECISION)

    # GPS jitter puts one address on both sides of a cell edge, so cells that share
    # an address are merged into one group (union-find).
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first_cell = {}
    for r in rows:
        find(r["geohash"])
        addr = r["address"].lower()
        if addr == PLACEHOLDER_ADDRESS:
            continue
        if addr in first_cell:
            parent[find(r["geohash"])] = find(first_cell[addr])
        else:
            first_cell[addr] = r["geohash"]
    for r in rows:
        r["group"] = find(r["geohash"])

    labels = [r["label"] for r in rows]
    groups = [r["group"] for r in rows]
    folds = np.empty(len(rows), dtype=int)
    sgkf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    for k, (_, idx) in enumerate(sgkf.split(np.zeros(len(rows)), labels, groups)):
        folds[idx] = k
    for r, f in zip(rows, folds):
        r["split"] = "test" if f == 0 else "val" if f == 1 else "train"

    # hard check: no cell or address spans two splits
    cell_splits, addr_splits = {}, {}
    for r in rows:
        cell_splits.setdefault(r["geohash"], set()).add(r["split"])
        if r["address"].lower() != PLACEHOLDER_ADDRESS:
            addr_splits.setdefault(r["address"].lower(), set()).add(r["split"])
    assert all(len(s) == 1 for s in cell_splits.values()), "cell spans splits"
    assert all(len(s) == 1 for s in addr_splits.values()), "address spans splits"

    print("hashing images ...", flush=True)
    for r in rows:
        r["dhash"] = dhash(DATA / r["path"])

    by = {s: [r for r in rows if r["split"] == s] for s in ("train", "val", "test")}
    test_h = [r["dhash"] for r in by["test"]]
    drop = set()
    for s in ("train", "val"):
        for i in near_dups([r["dhash"] for r in by[s]], test_h):
            drop.add(by[s][i]["service_request_id"])
    val_h = [r["dhash"] for r in by["val"] if r["service_request_id"] not in drop]
    for i in near_dups([r["dhash"] for r in by["train"]], val_h):
        drop.add(by["train"][i]["service_request_id"])
    print(f"near-duplicates dropped from train/val: {len(drop)}")

    n_before = len(drop)
    test_rows = by["test"]
    for s in ("train", "val"):
        for i in close_pairs(by[s], test_rows, BUFFER_M):
            drop.add(by[s][i]["service_request_id"])
    val_rows = [r for r in by["val"] if r["service_request_id"] not in drop]
    for i in close_pairs(by["train"], val_rows, BUFFER_M):
        drop.add(by["train"][i]["service_request_id"])
    print(f"same-class photos within {BUFFER_M} m of a held-out photo dropped: {len(drop) - n_before}")

    kept = [r for r in rows if r["service_request_id"] not in drop]
    cols = list(rows[0].keys())
    cols.remove("dhash")
    for r in kept:
        r["dhash"] = f"{r['dhash']:016x}"
    cols.append("dhash")

    manifest = {"seed": SEED, "geohash_precision": GEOHASH_PRECISION, "n_folds": N_FOLDS,
                "near_dup_bits": NEAR_DUP_BITS, "buffer_m": BUFFER_M,
                "input_rows": len(rows), "dropped": len(drop),
                "files": {}, "counts": {}}
    for name, subset in [("metadata.csv", kept)] + [
            (f"{s}.csv", [r for r in kept if r["split"] == s]) for s in ("train", "val", "test")]:
        with open(DATA / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(sorted(subset, key=lambda r: (r["label"], r["service_request_id"])))
        manifest["files"][name] = hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        manifest["counts"][name] = dict(sorted(Counter(r["label"] for r in subset).items()))
        manifest["counts"][name]["_total"] = len(subset)
        manifest["counts"][name]["_cells"] = len({r["geohash"] for r in subset})
    (DATA / "SPLIT_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")

    c = Counter((r["label"], r["split"]) for r in kept)
    print(f"{'label':20s} train   val  test  test%")
    for l in sorted({r["label"] for r in kept}):
        a, v, t = c[(l, "train")], c[(l, "val")], c[(l, "test")]
        print(f"{l:20s} {a:5d} {v:5d} {t:5d}  {100 * t / (a + v + t):4.1f}")
    for s in ("train", "val", "test"):
        print(s, manifest["counts"][f"{s}.csv"]["_total"], "images,",
              manifest["counts"][f"{s}.csv"]["_cells"], "cells")


if __name__ == "__main__":
    main()
