"""How much does GPS location alone tell us? (train -> val only; never touches test)

1. Category from location only: kNN (k=50) over train coordinates, scored on val.
   Val blocks are spatially separated from train, so this is a fair estimate.
2. Agency routing given the true category: the category's usual agency vs the
   agency of the nearest same-category train report.

Output: docs/evidence/location_signal.json
Run: python3 scripts/location_signal.py
"""
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
K = 50


def coords(rows):
    return np.radians([[float(r["lat"]), float(r["long"])] for r in rows])


def dist(a, b):
    return np.hypot(a[:, None, 0] - b[None, :, 0], (a[:, None, 1] - b[None, :, 1]) * np.cos(a[:, None, 0]))


def main():
    tr = list(csv.DictReader(open(ROOT / "data" / "train.csv")))
    va = list(csv.DictReader(open(ROOT / "data" / "val.csv")))
    labels = sorted({r["label"] for r in tr})
    idx = {l: i for i, l in enumerate(labels)}
    yt = np.array([idx[r["label"]] for r in tr])
    yv = np.array([idx[r["label"]] for r in va])
    xt, xv = coords(tr), coords(va)

    probs = np.zeros((len(va), len(labels)))
    for s in range(0, len(va), 512):
        nn = np.argpartition(dist(xv[s:s + 512], xt), K, axis=1)[:, :K]
        for j, row in enumerate(nn):
            probs[s + j] = np.bincount(yt[row], minlength=len(labels))
    rank = np.argsort(-probs, axis=1)
    top1 = float((rank[:, 0] == yv).mean())
    top3 = float(np.mean([yv[i] in rank[i, :3] for i in range(len(yv))]))

    usual = {l: Counter(r["agency_responsible"] for r in tr if r["label"] == l).most_common(1)[0][0] for l in labels}
    ok_usual = ok_nn = 0
    for l in labels:
        t = [r for r in tr if r["label"] == l]
        v = [r for r in va if r["label"] == l]
        nearest = dist(coords(v), coords(t)).argmin(axis=1)
        for r, j in zip(v, nearest):
            ok_usual += r["agency_responsible"] == usual[l]
            ok_nn += r["agency_responsible"] == t[j]["agency_responsible"]

    out = {
        "split": "train -> val (spatially separated)",
        "category_from_location_only": {"k": K, "val_top1": round(top1, 3), "val_top3": round(top3, 3),
                                        "chance_top1": round(1 / 17, 3), "chance_top3": round(3 / 17, 3)},
        "agency_given_true_category": {"usual_agency_for_category": round(ok_usual / len(va), 3),
                                       "nearest_same_category_report": round(ok_nn / len(va), 3)},
    }
    path = ROOT / "docs" / "evidence" / "location_signal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
