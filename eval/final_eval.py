"""B5: the ONE test-set evaluation, after A's ml/ freeze at G3 (PLAN 3.6).

This file is one of the two allow-listed test readers (scripts/guard_repo.py). It refuses to run
unless reports/TEST_LEDGER.md already has a line naming this script and the artifact version.

  python eval/final_eval.py --artifact artifacts/<final> [--geoprior artifacts/geoprior/geoprior.npz]
        [--probe runs/probes/<backbone>-<mode>] [--batch 64] [--n-boot 1000]

1. Predict all test images with A's `ml.infer.Predictor` (contracts/predictor.md). CUDA if present.
2. Full metrics at the calibrated temperature and abstain threshold from model_meta.json, with
   cluster-bootstrap CIs over `group`, WITH the geo-prior (beta from the artifact) and WITHOUT (beta 0).
3. On the pre-registered 1,020-id subset: the model, Claude zero-shot
   (reports/claude_baseline_predictions.csv, if it exists), the cascade (model, Claude when it
   abstains), and the best frozen probe (A's runs/probes/<x>/head.npz applied to test features
   extracted here with ml.data / ml.extract_features).
4. Writes reports/final_eval.json + reports/confusion_matrix.png. Commit untouched. A later run is post-hoc.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import metrics as M  # noqa: E402
from eval.val_report import confusion_png  # noqa: E402

DATA = ROOT / "data"
TEST_CSV = DATA / "test.csv"
SUBSET_IDS = ROOT / "reports" / "claude_baseline_ids.csv"
CLAUDE_PRED = ROOT / "reports" / "claude_baseline_predictions.csv"
LEDGER = ROOT / "reports" / "TEST_LEDGER.md"
REPORTS = ROOT / "reports"


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def ledger_ok(model_version: str) -> bool:
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    return any("final_eval.py" in line and model_version in line and line.startswith("|") for line in text.splitlines())


def predict_logits(artifact: Path, paths: list[str], batch: int) -> np.ndarray:
    from ml.infer import Predictor  # A's lane; only imported here
    p = Predictor.from_artifact(str(artifact))
    out = []
    t0 = time.time()
    for i in range(0, len(paths), batch):
        out.append(np.asarray(p.logits(paths[i:i + batch]), dtype=np.float64))
        if (i // batch) % 10 == 0:
            print(f"  {i + len(out[-1])}/{len(paths)} images, {time.time() - t0:.0f}s", file=sys.stderr)
    return np.concatenate(out)


def probe_logits(probe_dir: Path, paths: list[str], batch: int) -> tuple[np.ndarray, str]:
    """A's frozen probe applied to test features extracted here (never by A)."""
    import torch
    from ml.data import BACKBONES, create_model, eval_transform, norm_stats, output_size, pick_device
    from ml.extract_features import extract

    head = np.load(probe_dir / "head.npz", allow_pickle=False)
    timm_name, crop_mode = str(head["timm_name"]), str(head["crop_mode"])
    backbone = next(k for k, v in BACKBONES.items() if v["timm_name"] == timm_name)
    device = pick_device()
    model = create_model(backbone, crop_mode).eval().to(device)
    if device.type == "mps":
        model = model.half()
    mean, std = norm_stats(model)
    w, h = output_size(backbone, crop_mode)
    rows = [{"path": p, "label": M.class_labels()[0]} for p in paths]  # label unused for features
    feats = extract(model, rows, eval_transform(w, h, mean, std), device, batch, 0)
    logits = feats @ head["weight"].T.astype(np.float64) + head["bias"].astype(np.float64)
    return logits, f"probe-{backbone}-{crop_mode}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--geoprior", type=Path, help="A's geoprior.npz; beta is read from the artifact")
    ap.add_argument("--probe", type=Path, help="runs/probes/<backbone>-<mode> (head.npz) for the frozen-probe baseline")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--post-hoc", action="store_true", help="label this run post-hoc (any run after the first)")
    ap.add_argument("--logits-cache", type=Path, help="npz to save/load raw test logits (resume after a crash)")
    args = ap.parse_args()

    meta = json.loads((args.artifact / "model_meta.json").read_text(encoding="utf-8"))
    mv = meta["model_version"]
    if not ledger_ok(mv):
        print("Add this line to reports/TEST_LEDGER.md and commit it BEFORE running:\n", file=sys.stderr)
        print(f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | B | eval/final_eval.py | {git_sha()} | {mv} | "
              f"final test evaluation after ml/ freeze{' (post-hoc)' if args.post_hoc else ''} | {'no' if args.post_hoc else 'yes'} |",
              file=sys.stderr)
        return 2
    if meta["temperature"] is None or meta["abstain_threshold"] is None:
        raise SystemExit("artifact is not calibrated; run eval/calibrate.py first")
    names = M.class_labels()
    if meta["classes"] != names:
        raise SystemExit("model_meta.classes != contracts/categories.json")
    T, tau = float(meta["temperature"]), float(meta["abstain_threshold"])
    beta = float(meta.get("geo_prior_beta", meta.get("val_metrics", {}).get("geo_prior_beta", 0.0)) or 0.0)

    test = pd.read_csv(TEST_CSV, dtype={"service_request_id": str})
    idx = {l: i for i, l in enumerate(names)}
    labels = test["label"].map(idx).to_numpy()
    groups = test["group"].to_numpy()
    paths = [str(DATA / p) for p in test["path"]]
    print(f"test: {len(test)} images, {len(np.unique(groups))} groups; artifact {mv} T={T:.3f} tau={tau:.3f} beta={beta:g}",
          file=sys.stderr)

    if args.logits_cache and args.logits_cache.exists():
        logits = np.load(args.logits_cache)["logits"]
    else:
        logits = predict_logits(args.artifact, paths, args.batch)
        if args.logits_cache:
            np.savez(args.logits_cache, logits=logits.astype(np.float32), ids=test["service_request_id"].to_numpy().astype(str))
    assert logits.shape == (len(test), 17)

    result: dict = {
        "model_version": mv, "git_sha": git_sha(), "when": datetime.now().isoformat(timespec="seconds"),
        "post_hoc": bool(args.post_hoc), "n_test": int(len(test)), "temperature": T, "abstain_threshold": tau,
        "geo_prior_beta": beta, "source": "data/test.csv (frozen; SPLIT_MANIFEST.json)",
    }
    # --- with / without the geo-prior ----------------------------------------------------
    L = None
    if args.geoprior and beta:
        from eval.geo import GeoPrior, fuse
        gp = GeoPrior(args.geoprior)
        L = gp.log_lift_batch(test["lat"].to_numpy(), test["long"].to_numpy())
        result["geo_prior_cell_coverage"] = gp.coverage(test["lat"].to_numpy(), test["long"].to_numpy())
        fused = fuse(logits, L, beta)
        result["with_geo_prior"] = M.summarize(fused, labels, groups=groups, temperature=T, threshold=tau,
                                               prior=M.real_prior(), n_boot=args.n_boot, labels_names=names)
    result["without_geo_prior"] = M.summarize(logits, labels, groups=groups, temperature=T, threshold=tau,
                                              prior=M.real_prior(), n_boot=args.n_boot, labels_names=names)
    headline = result.get("with_geo_prior", result["without_geo_prior"])
    result["headline"] = "with_geo_prior" if "with_geo_prior" in result else "without_geo_prior"
    result["top_confusions"] = M.top_confusions(np.array(headline["confusion_matrix"]), names, k=5)
    confusion_png(np.array(headline["confusion_matrix"]), names, REPORTS / "confusion_matrix.png",
                  f"{mv} (test, {result['headline']}, T={T:.2f})")

    # --- the 1,020-image subset: model vs Claude vs cascade vs frozen probe ----------------
    sub_ids = pd.read_csv(SUBSET_IDS, dtype={"service_request_id": str})["service_request_id"]
    pos = pd.Series(np.arange(len(test)), index=test["service_request_id"]).reindex(sub_ids).to_numpy()
    if np.isnan(pos).any():
        raise SystemExit("subset ids not all in the test split")
    pos = pos.astype(int)
    sub_logits = (fuse(logits, L, beta) if L is not None else logits)[pos]
    sub_labels, sub_groups = labels[pos], groups[pos]
    probs = M.softmax(sub_logits, T)
    model_pred = probs.argmax(1)
    abstain = probs.max(1) < tau
    subset: dict = {
        "n": int(len(pos)), "ids_file": str(SUBSET_IDS.relative_to(ROOT)),
        "model": M.summarize(sub_logits, sub_labels, groups=sub_groups, temperature=T, threshold=tau, n_boot=args.n_boot, labels_names=names),
        "chance_top1": 1 / 17,
    }
    for k in ("per_class", "confusion_matrix"):
        subset["model"].pop(k, None)
    subset["model"]["abstain_rate"] = float(abstain.mean())
    if CLAUDE_PRED.exists():
        cp = pd.read_csv(CLAUDE_PRED, dtype={"service_request_id": str}).set_index("service_request_id").reindex(sub_ids)
        claude_pred = np.array([idx.get(p, -1) if isinstance(p, str) else -1 for p in cp["pred"]])
        claude_safe = np.where(claude_pred >= 0, claude_pred, (sub_labels + 1) % 17)  # wrong when missing/refused
        subset["claude_zeroshot"] = {
            "top1": float((claude_safe == sub_labels).mean()), "macro_f1": M.macro_f1(claude_safe, sub_labels),
            "n_answered": int((claude_pred >= 0).sum()),
            "ci95": {"top1": list(M.cluster_bootstrap_ci(lambda i: float((claude_safe[i] == sub_labels[i]).mean()), sub_groups, args.n_boot)),
                     "macro_f1": list(M.cluster_bootstrap_ci(lambda i: M.macro_f1(claude_safe[i], sub_labels[i]), sub_groups, args.n_boot))},
            "source": str(CLAUDE_PRED.relative_to(ROOT)),
        }
        cascade = np.where(abstain, claude_safe, model_pred)
        subset["cascade_model_then_claude_on_abstain"] = {
            "top1": float((cascade == sub_labels).mean()), "macro_f1": M.macro_f1(cascade, sub_labels),
            "claude_used_rate": float(abstain.mean()),
            "ci95": {"top1": list(M.cluster_bootstrap_ci(lambda i: float((cascade[i] == sub_labels[i]).mean()), sub_groups, args.n_boot))},
        }
    else:
        subset["claude_zeroshot"] = {"note": f"{CLAUDE_PRED.relative_to(ROOT)} not found; run eval/claude_zeroshot.py test first"}
    if args.probe:
        try:
            pl, pname = probe_logits(args.probe, [paths[i] for i in pos], args.batch)
            s = M.summarize(pl, sub_labels, groups=sub_groups, temperature=1.0, n_boot=args.n_boot, labels_names=names)
            for k in ("per_class", "confusion_matrix"):
                s.pop(k, None)
            subset["best_frozen_probe"] = s | {"probe": pname, "head": str(args.probe)}
        except Exception as e:  # torch / timm missing on this machine
            subset["best_frozen_probe"] = {"note": f"probe baseline skipped: {type(e).__name__}: {e}"}
    result["subset_1020"] = subset

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / ("final_eval_posthoc.json" if args.post_hoc else "final_eval.json")
    if out.exists() and not args.post_hoc:
        raise SystemExit(f"{out} exists. The first run is the result; re-runs must pass --post-hoc.")
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    h = headline
    sel = h["selective"]
    print(f"\n{mv} on test (n={len(test)}), {result['headline']}:")
    print(f"  top-1 {h['top1']:.4f} [{h['ci95']['top1'][0]:.4f}, {h['ci95']['top1'][1]:.4f}]   top-3 {h['top3']:.4f}")
    print(f"  macro-F1 {h['macro_f1']:.4f} [{h['ci95']['macro_f1'][0]:.4f}, {h['ci95']['macro_f1'][1]:.4f}]   ECE {h['ece']:.4f}   AURC {h['aurc']:.4f}")
    print(f"  at tau={tau:.3f}: coverage {sel['coverage']:.1%} [{h['ci95']['coverage'][0]:.1%}, {h['ci95']['coverage'][1]:.1%}], "
          f"selective acc {sel['selective_accuracy']:.4f} (lower-95% {sel['selective_accuracy_lower95']:.4f})")
    if "with_geo_prior" in result:
        w = result["without_geo_prior"]
        print(f"  without geo-prior: top-1 {w['top1']:.4f}  macro-F1 {w['macro_f1']:.4f}")
    cz = subset.get("claude_zeroshot", {})
    if "top1" in cz:
        print(f"  subset n={subset['n']}: model {subset['model']['top1']:.4f} | Claude zero-shot {cz['top1']:.4f} | "
              f"cascade {subset['cascade_model_then_claude_on_abstain']['top1']:.4f}")
    print(f"  wrote {out} and reports/confusion_matrix.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
