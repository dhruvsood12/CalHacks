"""Geo-prior table (PLAN §3.7): how much more common each class is in a ~1 km cell than citywide.

Built ONLY from DataSF cases filed before the dataset window (2022-10-01 .. 2024-09-30), so no
train/val/test case and nothing from the future is in it. Stored as log-lift:
    log L(c|cell) = log p(c|cell) - log p(c),  p(c|cell) = (n_cell,c + alpha p(c)) / (n_cell + alpha)
Lift is used rather than raw frequency so the prior encodes "more common here than usual",
not "garbage is common everywhere"; a class-wide undercount (older category names) cancels out.

Build:  python -m ml.geoprior --build      -> artifacts/geoprior/geoprior.npz (cells, log_lift)
Use:    from ml.geoprior import log_lift; log_lift(37.77, -122.42) -> (17,) array, 0 for unknown cells
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache

import numpy as np

from ml.data import CLASSES, ROOT

API = "https://data.sf.gov/resource/vw6y-z8j6.json"
START, END = "2022-10-01", "2024-10-01"  # END is the dataset window's first day; exclusive
PRECISION = 6
ALPHA = 20.0
OUT = ROOT / "artifacts" / "geoprior" / "geoprior.npz"
_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat, lng, precision=PRECISION):
    lat_r, lng_r = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, ch, even = [], 0, 0, True
    while len(out) < precision:
        rng, val = (lng_r, lng) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch, rng[0] = (ch << 1) | 1, mid
        else:
            ch, rng[1] = ch << 1, mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_B32[ch])
            bits, ch = 0, 0
    return "".join(out)


def fetch_class(item):
    label, cond = item
    where = (f"({cond}) AND requested_datetime >= '{START}' AND requested_datetime < '{END}' "
             f"AND lat IS NOT NULL")
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"$select": "lat,long,requested_datetime", "$where": where,
                                    "$order": "service_request_id", "$limit": 50000, "$offset": offset})
        with urllib.request.urlopen(f"{API}?{q}", timeout=300) as r:
            page = json.load(r)
        rows += page
        if len(page) < 50000:
            break
        offset += 50000
    late = [r for r in rows if r["requested_datetime"][:10] >= END]
    assert not late, f"{label}: {len(late)} rows on/after {END}; the prior must not see the dataset window"
    return label, [(float(r["lat"]), float(r["long"])) for r in rows if float(r["lat"]) > 37]


def build():
    sys.path.insert(0, str(ROOT / "scripts"))
    from scrape_sf311 import CLASSES as FILTERS

    with ThreadPoolExecutor(6) as ex:
        pulled = dict(ex.map(fetch_class, FILTERS.items()))
    cells = sorted({geohash(lat, lng) for pts in pulled.values() for lat, lng in pts})
    index = {c: i for i, c in enumerate(cells)}
    counts = np.zeros((len(cells), len(CLASSES)))
    for label, pts in pulled.items():
        k = CLASSES.index(label)
        for cell, n in Counter(geohash(lat, lng) for lat, lng in pts).items():
            counts[index[cell], k] += n
    p_city = counts.sum(0) / counts.sum()
    p_cell = (counts + ALPHA * p_city) / (counts.sum(1, keepdims=True) + ALPHA)
    table = np.log(p_cell / p_city).astype(np.float32)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez(OUT, cells=np.array(cells), log_lift=table, classes=np.array(CLASSES),
             n_per_class=counts.sum(0).astype(np.int64), window=np.array([START, END]), alpha=ALPHA,
             precision=PRECISION, built=datetime.now().isoformat(timespec="seconds"))
    print(f"wrote {OUT}: {len(cells)} cells x {len(CLASSES)} classes from {int(counts.sum())} cases "
          f"filed {START} .. before {END}")
    print("log-lift range:", float(table.min()), float(table.max()))


@lru_cache(maxsize=1)
def _load():
    z = np.load(OUT, allow_pickle=False)
    return {str(c): i for i, c in enumerate(z["cells"].tolist())}, z["log_lift"]


def log_lift(lat, lng):
    index, table = _load()
    i = index.get(geohash(lat, lng))
    return table[i].astype(np.float32) if i is not None else np.zeros(len(CLASSES), dtype=np.float32)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    if ap.parse_args().build:
        build()
