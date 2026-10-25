"""B2: the val dashboard. One row per training run, with cluster-bootstrap CIs, plus
optional ensemble rows. Decides crop mode, recipe, ensemble membership and TTA (PLAN 3.4).

Usage:
  python eval/val_report.py --runs runs/<run1>/val_logits.npz runs/<run2>/val_logits.npz ...
      [--ensemble]            # also score the average of all given runs
      [--greedy]              # greedy forward selection: add a run only if val macro-F1 improves
      [--geoprior artifacts/geoprior/geoprior.npz --beta 0.5]   # score with the geo-prior fused
      [--n-boot 1000] [--out reports]

Writes reports/val_<run>.json (+ reports/val_<run>_confusion.png) per row and prints a
markdown table for team chat. Every number on a slide comes from one of these JSON files.

Reads data/val.csv only. Never the test split.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import metrics as M  # noqa: E402

VAL_CSV = ROOT / "data" / "val.csv"


def load_val() -> pd.DataFrame:
    df = pd.read_csv(VAL_CSV, dtype={"service_request_id": str})
    labels = M.class_labels()
    idx = {l: i for i, l in enumerate(labels)}
    df["label_idx"] = df["label"].map(idx)
    if df["label_idx"].isna().any():
        bad = df.loc[df["label_idx"].isna(), "label"].unique()
        raise SystemExit(f"val labels not in categories.json: {bad}")
    return df.set_index("service_request_id")


def load_run(path: Path, val: pd.DataFrame) -> tuple[str, str, np.ndarray, np.ndarray]:
    """Return (run_name, timm_name, logits aligned to `val` order, labels). Checks N, ids, labels."""
    z = np.load(path, allow_pickle=False)
    ids = np.asarray(z["ids"]).astype(str)
    logits = np.asarray(z["logits"], dtype=np.float64)
    labels = np.asarray(z["labels"]).astype(int)
    run = str(z["run"]) if "run" in z.files else path.parent.name
    timm_name = str(z["timm_name"]) if "timm_name" in z.files else ""
    if len(ids) != len(val):
        raise SystemExit(f"{path}: N={len(ids)} but val has {len(val)} rows (contracts/predictor.md)")
    if logits.shape != (len(val), M.N_CLASSES):
        raise SystemExit(f"{path}: logits shape {logits.shape} != ({len(val)}, {M.N_CLASSES})")
    missing = set(val.index) - set(ids)
    if missing:
        raise SystemExit(f"{path}: {len(missing)} val ids missing from the npz, e.g. {sorted(missing)[:3]}")
    order = pd.Series(np.arange(len(ids)), index=ids).reindex(val.index).to_numpy()
    logits, labels = logits[order], labels[order]
    if not (labels == val["label_idx"].to_numpy()).all():
        n = int((labels != val["label_idx"].to_numpy()).sum())
        raise SystemExit(f"{path}: {n} labels disagree with data/val.csv; check class order against categories.json")
    return run, timm_name, logits, labels


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "-", s).strip("-")


def confusion_png(cm: np.ndarray, names: list[str], out: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cmn = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(cmn, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(names)), names, rotation=70, ha="right", fontsize=8)
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title)
    for i in range(len(names)):
        for j in range(len(names)):
            if cm[i, j]:
                ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=6,
                        color="white" if cmn[i, j] > 0.5 else "black")
    fig.colorbar(im, ax=ax, fraction=0.03)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def score(name: str, logits: np.ndarray, val: pd.DataFrame, n_boot: int, out_dir: Path,
          members: list[str] | None = None, extra: dict | None = None) -> dict:
    names = M.class_labels()
    labels = val["label_idx"].to_numpy()
    groups = val["group"].to_numpy()
    T = M.fit_temperature(logits, labels)
    probs_T = M.softmax(logits, T)
    thr = M.abstain_threshold(probs_T, labels, target=0.90)
    s = M.summarize(logits, labels, groups=groups, temperature=T, threshold=thr["threshold"],
                    prior=M.real_prior(), n_boot=n_boot, labels_names=names)
    s["run"] = name
    s["members"] = members or [name]
    s["abstain_rule"] = thr
    s["source"] = "data/val.csv"
    if extra:
        s.update(extra)
    # error analysis: top-5 confused pairs with up to 3 example paths each (never encampment)
    cm = np.array(s["confusion_matrix"])
    preds = probs_T.argmax(axis=1)
    confs = M.top_confusions(cm, names, k=5)
    for c in confs:
        t, p = names.index(c["true"]), names.index(c["pred"])
        if "encampment" in (c["true"], c["pred"]):
            c["examples"], c["examples_note"] = [], "omitted: encampment photos show people (PLAN 9)"
            continue
        m = (labels == t) & (preds == p)
        c["examples"] = val.loc[m, "path"].head(3).tolist()
    s["top_confusions"] = confs
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"val_{safe_name(name)}"
    (out_dir / f"{stem}.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    try:
        confusion_png(cm, names, out_dir / f"{stem}_confusion.png", f"{name} (val, T={T:.2f})")
    except Exception as e:  # matplotlib is optional at runtime
        print(f"  (no confusion PNG: {type(e).__name__}: {e})", file=sys.stderr)
    return s


def row(s: dict) -> str:
    ci = s.get("ci95", {})

    def f(k, scale=100, nd=1):
        v = s[k] * scale
        if k in ci:
            lo, hi = ci[k]
            return f"{v:.{nd}f} [{lo * scale:.{nd}f}, {hi * scale:.{nd}f}]"
        return f"{v:.{nd}f}"

    sel = s.get("selective", {})
    return (f"| {s['run']} | {f('macro_f1')} | {f('top1')} | {f('top3')} | {f('aurc', 1, 3)} | "
            f"{s['ece_uncalibrated'] * 100:.1f} -> {s['ece'] * 100:.1f} | {s['temperature']:.2f} | "
            f"{s['abstain_rule']['threshold']:.3f} | {sel.get('coverage', float('nan')) * 100:.1f}% | "
            f"{s.get('prior_weighted_top1', float('nan')) * 100:.1f} |")


HEADER = ("| run | macro-F1 [95% CI] | top-1 [CI] | top-3 [CI] | AURC [CI] | ECE raw -> T | T | tau90 | "
          "coverage@tau90 | prior-wtd top-1 |\n|---|---|---|---|---|---|---|---|---|---|")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, type=Path, help="val_logits.npz files")
    ap.add_argument("--ensemble", action="store_true", help="also score the ensemble of all runs")
    ap.add_argument("--greedy", action="store_true", help="greedy forward selection by val macro-F1")
    ap.add_argument("--geoprior", type=Path, help="artifacts/geoprior/geoprior.npz (fuse with --beta)")
    ap.add_argument("--beta", type=float, default=0.0)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    args = ap.parse_args()

    val = load_val()
    runs: dict[str, np.ndarray] = {}
    meta: dict[str, str] = {}
    for p in args.runs:
        name, timm_name, logits, _ = load_run(p, val)
        if name in runs:
            name = f"{name}@{p.parent.name}"
        runs[name], meta[name] = logits, timm_name
        print(f"loaded {p} -> {name} ({timm_name})", file=sys.stderr)

    extra = {}
    if args.geoprior and args.beta:
        from eval.geo import GeoPrior, fuse
        gp = GeoPrior(args.geoprior)
        L = gp.log_lift_batch(val["lat"].to_numpy(), val["long"].to_numpy())
        runs = {k + f"+geo{args.beta:g}": fuse(v, L, args.beta) for k, v in runs.items()}
        extra = {"geo_prior_beta": args.beta, "geo_prior": str(args.geoprior),
                 "geo_prior_cell_coverage": gp.coverage(val["lat"].to_numpy(), val["long"].to_numpy())}

    rows = []
    for name, logits in runs.items():
        s = score(name, logits, val, args.n_boot, args.out, extra={**extra, "timm_name": meta.get(name.split("+geo")[0], "")})
        rows.append(s)
        print(f"  {name}: macro-F1 {s['macro_f1']:.4f}  top-1 {s['top1']:.4f}  AURC {s['aurc']:.4f}", file=sys.stderr)

    if args.ensemble and len(runs) > 1:
        ens = M.ensemble_logits(list(runs.values()))
        rows.append(score("ens(" + "+".join(runs) + ")", ens, val, args.n_boot, args.out, members=list(runs), extra=extra))

    if args.greedy and len(runs) > 1:
        labels = val["label_idx"].to_numpy()
        f1 = {k: M.macro_f1(v.argmax(1), labels) for k, v in runs.items()}
        chosen = [max(f1, key=f1.get)]
        best = f1[chosen[0]]
        while True:
            cands = {k: M.macro_f1(M.ensemble_logits([runs[c] for c in chosen + [k]]).argmax(1), labels)
                     for k in runs if k not in chosen}
            if not cands:
                break
            k = max(cands, key=cands.get)
            if cands[k] <= best + 1e-9:
                break
            chosen.append(k)
            best = cands[k]
        print(f"greedy ensemble (val macro-F1): {chosen} -> {best:.4f}", file=sys.stderr)
        if len(chosen) > 1:
            rows.append(score("greedy(" + "+".join(chosen) + ")", M.ensemble_logits([runs[c] for c in chosen]),
                              val, args.n_boot, args.out, members=chosen, extra={**extra, "greedy_order": chosen}))

    print("\n" + HEADER)
    for s in rows:
        print(row(s))
    print(f"\n(val, n={len(val)}, {rows[0]['n_groups']} groups, {args.n_boot} bootstrap resamples; "
          f"tau90 = smallest threshold whose Clopper-Pearson lower-95% bound on selective accuracy >= 0.90; "
          f"files: {args.out}/val_<run>.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
