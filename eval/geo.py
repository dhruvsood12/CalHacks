"""Geo-prior helpers for B (PLAN 3.7): geohash encoding and the log-lift table A builds.

A's `ml/geoprior.py` writes `artifacts/geoprior/geoprior.npz` with the per-cell log-lift
table (cells x 17) and the list of geohash-6 cells. This module reads that file without
importing `ml/`, so B can tune beta on val with nothing but the npz and the split CSV.

Fusion (PLAN 3.7): log p(c | img, loc) = log p(c | img) + beta * log_lift[cell, c], applied
before the temperature. beta = 0 means off. Unknown or missing cells contribute 0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(lat: float, lng: float, precision: int = 6) -> str:
    """Standard geohash (Niemeyer) of a WGS84 point."""
    lat_lo, lat_hi, lng_lo, lng_hi = -90.0, 90.0, -180.0, 180.0
    out, bit, ch, even = [], 0, 0, True
    while len(out) < precision:
        if even:
            mid = (lng_lo + lng_hi) / 2
            if lng >= mid:
                ch |= 1 << (4 - bit)
                lng_lo = mid
            else:
                lng_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= 1 << (4 - bit)
                lat_lo = mid
            else:
                lat_hi = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_BASE32[ch])
            bit, ch = 0, 0
    return "".join(out)


class GeoPrior:
    """The log-lift table. Accepts a few key spellings so A's export needs no coordination:
    cells under `cells` / `cell_ids` / `geohash`, lift under `log_lift` / `loglift` (or `lift`,
    which is logged here)."""

    def __init__(self, path: str | Path, precision: int | None = None):
        z = np.load(Path(path), allow_pickle=False)
        keys = set(z.files)
        cell_key = next((k for k in ("cells", "cell_ids", "geohash", "geohashes") if k in keys), None)
        if cell_key is None:
            raise KeyError(f"geoprior npz has no cell list; keys = {sorted(keys)}")
        if "log_lift" in keys:
            table = np.asarray(z["log_lift"], dtype=np.float64)
        elif "loglift" in keys:
            table = np.asarray(z["loglift"], dtype=np.float64)
        elif "lift" in keys:
            table = np.log(np.clip(np.asarray(z["lift"], dtype=np.float64), 1e-9, None))
        else:
            raise KeyError(f"geoprior npz has no log_lift table; keys = {sorted(keys)}")
        cells = [str(c) for c in z[cell_key].tolist()]
        if table.shape[0] != len(cells):
            raise ValueError(f"log_lift rows {table.shape[0]} != cells {len(cells)}")
        self.n_classes = int(table.shape[1])
        self.table = table
        self.index = {c: i for i, c in enumerate(cells)}
        self.precision = precision or len(cells[0])
        self.alpha = float(z["alpha"]) if "alpha" in keys else None

    def log_lift(self, lat: float | None, lng: float | None) -> np.ndarray:
        """(17,) log-lift for one point; zeros for unknown cells or missing coordinates."""
        if lat is None or lng is None or not np.isfinite(lat) or not np.isfinite(lng):
            return np.zeros(self.n_classes)
        i = self.index.get(geohash_encode(float(lat), float(lng), self.precision))
        return self.table[i] if i is not None else np.zeros(self.n_classes)

    def log_lift_batch(self, lats, lngs) -> np.ndarray:
        lats, lngs = np.asarray(lats, dtype=np.float64), np.asarray(lngs, dtype=np.float64)
        return np.stack([self.log_lift(a, b) for a, b in zip(lats, lngs)])

    def coverage(self, lats, lngs) -> float:
        """Share of points whose cell is in the table."""
        lats, lngs = np.asarray(lats, dtype=np.float64), np.asarray(lngs, dtype=np.float64)
        hits = [geohash_encode(a, b, self.precision) in self.index
                for a, b in zip(lats, lngs) if np.isfinite(a) and np.isfinite(b)]
        return float(np.mean(hits)) if hits else 0.0


def fuse(logits: np.ndarray, log_lift: np.ndarray, beta: float) -> np.ndarray:
    """logits (N,17) + beta * log_lift (N,17). Pass the result to the temperature / softmax."""
    if beta == 0:
        return np.asarray(logits, dtype=np.float64)
    return np.asarray(logits, dtype=np.float64) + float(beta) * np.asarray(log_lift, dtype=np.float64)
