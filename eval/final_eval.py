"""B5: the ONE test-set evaluation, after A's ml/ freeze at G3 (PLAN 3.6).

This file is one of the two allow-listed test readers (scripts/guard_repo.py).

  python eval/final_eval.py --artifact artifacts/<final> --geoprior artifacts/geoprior/geoprior.npz
        --probe runs/probes/<backbone>-<mode> [--batch 64] [--n-boot 1000] [--parity 64]

Everything that can fail is checked BEFORE any test data is read (pre-flight):
  - reports/TEST_LEDGER.md has a row naming this script and the artifact's model_version
    (a re-run needs --post-hoc and a row containing "post-hoc"),
  - the output file does not exist yet (post-hoc runs write final_eval_posthoc.json),
  - the artifact is calibrated and loads in ml.infer.Predictor,
  - --geoprior is given and loads whenever the artifact's geo_prior_beta > 0,
  - the Claude baseline predictions exist (reports/claude_baseline_predictions.csv; --without-claude
    to skip, recorded in the JSON),
  - the frozen probe head loads and its backbone builds (--without-probe to skip, recorded),
  - parity check on VAL images that are present locally: this script's fusion + temperature must
    match Predictor.probs(paths, latlng) to 1e-4,
  - every test image file is present.
Then: predict all test images once, score at the calibrated temperature and abstain threshold
WITH the geo-prior (headline, beta from the artifact) and WITHOUT (beta 0), cluster-bootstrap CIs;
on the pre-registered 1,020-id subset: model vs Claude zero-shot vs the cascade (model, Claude
when it abstains) vs the best frozen probe. Claude's refusals are an 18th "no answer" column.
Writes reports/final_eval.json + reports/confusion_matrix.png. Commit untouched.
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
from eval.geo import GeoPrior, fuse  # noqa: E402
from eval.val_report import confusion_png  # noqa: E402

DATA = ROOT / "data"
TEST_CSV = DATA / "test.csv"
SUBSET_IDS = ROOT / "reports" / "claude_baseline_ids.csv"
CLAUDE_PRED = ROOT / "reports" / "claude_baseline_predictions.csv"
DEV_IDS = ROOT / "reports" / "claude_prompt_dev_ids.csv"  # val ids, used only for the parity check
LEDGER = ROOT / "reports" / "TEST_LEDGER.md"
REPORTS = ROOT / "reports"


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def ledger_row(model_version: str, post_hoc: bool) -> str | None:
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    for line in text.splitlines():
        if line.startswith("|") and "final_eval.py" in line and model_version in line and (("post-hoc" in line.lower()) == post_hoc):
            return line
    return None


# ----------------------------------------------------------------------------
# A's code, loaded up front so any failure happens before test is read
# ----------------------------------------------------------------------------
def load_predictor(artifact: Path):
    from ml.infer import Predictor  # A's lane; only imported here
    return Predictor.from_artifact(str(artifact))


class Probe:
    """A's frozen linear probe (runs/probes/<x>/head.npz) on features extracted here."""

    def __init__(self, probe_dir: Path, batch: int):
        import torch  # noqa: F401
        from ml.data import BACKBONES, create_model, eval_transform, norm_stats, output_size, pick_device
        from ml.extract_features import extract

        head = np.load(probe_dir / "head.npz", allow_pickle=False)
        self.weight, self.bias = head["weight"].astype(np.float64), head["bias"].astype(np.float64)
        self.timm_name, self.crop_mode = str(head["timm_name"]), str(head["crop_mode"])
        self.backbone = next(k for k, v in BACKBONES.items() if v["timm_name"] == self.timm_name)
        self.name = f"probe-{self.backbone}-{self.crop_mode}"
        self.device = pick_device()
        self.model = create_model(self.backbone, self.crop_mode).eval().to(self.device)
        if self.device.type == "mps":
            self.model = self.model.half()
        mean, std = norm_stats(self.model)
        w, h = output_size(self.backbone, self.crop_mode)
        self.transform = eval_transform(w, h, mean, std)
        self.extract, self.batch = extract, batch
        if self.weight.shape != (M.N_CLASSES, self.model.num_features):
            raise SystemExit(f"probe head {self.weight.shape} does not match {self.backbone} features")

    def logits(self, paths: list[str]) -> np.ndarray:
        rows = [{"path": p, "label": M.class_labels()[0]} for p in paths]  # label unused for features
        feats = self.extract(self.model, rows, self.transform, self.device, self.batch, 0)
        return feats @ self.weight.T + self.bias


def predict_logits(predictor, paths: list[str], batch: int) -> np.ndarray:
    out, t0 = [], time.time()
    for i in range(0, len(paths), batch):
        out.append(np.asarray(predictor.logits(paths[i:i + batch]), dtype=np.float64))
        if (i // batch) % 10 == 0:
            print(f"  {min(i + batch, len(paths))}/{len(paths)} images, {time.time() - t0:.0f}s", file=sys.stderr)
    return np.concatenate(out)


def parity_check(predictor, gp: GeoPrior | None, beta: float, T: float, n: int, batch: int) -> dict:
    """On up to n VAL images present locally: our fusion+temperature vs Predictor.probs. Never test."""
    ids = pd.read_csv(DEV_IDS, dtype={"service_request_id": str})
    val = pd.read_csv(DATA / "val.csv", dtype={"service_request_id": str}).set_index("service_request_id")
    present = [i for i in ids["service_request_id"] if (DATA / val.loc[i, "path"]).exists()][:n]
    if not present:
        raise SystemExit("parity check needs local val images: python scripts/fetch_images.py --ids reports/claude_prompt_dev_ids.csv")
    paths = [str(DATA / val.loc[i, "path"]) for i in present]
    latlng = [(float(val.loc[i, "lat"]), float(val.loc[i, "long"])) for i in present]
    ours = np.asarray(predictor.logits(paths, batch), dtype=np.float64)
    if gp is not None and beta:
        ours = fuse(ours, gp.log_lift_batch([a for a, _ in latlng], [b for _, b in latlng]), beta)
    ours = M.softmax(ours, T)
    theirs = np.asarray(predictor.probs(paths, latlng=latlng if beta else None, batch=batch), dtype=np.float64)
    diff = float(np.abs(ours - theirs).max())
    if diff > 1e-4:
        raise SystemExit(f"parity check FAILED: max |ours - Predictor.probs| = {diff:.2e} on {len(present)} val images. "
                         "Fusion/temperature in this script disagree with ml/infer.py; fix before touching test.")
    return {"n_val_images": len(present), "max_abs_diff": diff}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--geoprior", type=Path, help="A's geoprior.npz; required when the artifact's geo_prior_beta > 0")
    ap.add_argument("--probe", type=Path, help="runs/probes/<backbone>-<mode> (head.npz): the frozen-probe baseline")
    ap.add_argument("--without-probe", action="store_true", help="explicitly skip the probe baseline (recorded)")
    ap.add_argument("--without-claude", action="store_true", help="explicitly skip the Claude baseline + cascade (recorded)")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--parity", type=int, default=64, help="val images for the Predictor parity check")
    ap.add_argument("--post-hoc", action="store_true", help="a re-run: needs its own 'post-hoc' ledger row")
    ap.add_argument("--logits-cache", type=Path, help="npz to save/load raw test logits (resume after a crash)")
    args = ap.parse_args()

    # ======================= pre-flight: nothing below reads test data =======================
    meta = json.loads((args.artifact / "model_meta.json").read_text(encoding="utf-8"))
    mv = meta["model_version"]
    out = REPORTS / ("final_eval_posthoc.json" if args.post_hoc else "final_eval.json")
    if out.exists():
        raise SystemExit(f"{out.relative_to(ROOT)} exists. The first run is the result; a re-run needs --post-hoc"
                         + (" (and final_eval_posthoc.json also exists)" if args.post_hoc else ""))
    row = ledger_row(mv, args.post_hoc)
    if row is None:
        print("Add this line to reports/TEST_LEDGER.md and commit it BEFORE running:\n", file=sys.stderr)
        print(f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | B | eval/final_eval.py | {git_sha()} | {mv} | "
              f"final test evaluation after ml/ freeze{' POST-HOC re-run' if args.post_hoc else ''} | "
              f"{'no (post-hoc)' if args.post_hoc else 'yes'} |", file=sys.stderr)
        return 2
    if meta["temperature"] is None or meta["abstain_threshold"] is None:
        raise SystemExit("artifact is not calibrated; run eval/calibrate.py first")
    names = M.class_labels()
    if meta["classes"] != names:
        raise SystemExit("model_meta.classes != contracts/categories.json")
    T, tau = float(meta["temperature"]), float(meta["abstain_threshold"])
    beta = float(meta.get("geo_prior_beta") or 0.0)
    gp = None
    if beta > 0:
        if not args.geoprior:
            raise SystemExit(f"artifact has geo_prior_beta={beta:g}: pass --geoprior (the headline is WITH the prior)")
        gp = GeoPrior(args.geoprior)
    if not args.without_claude and not CLAUDE_PRED.exists():
        raise SystemExit(f"{CLAUDE_PRED.relative_to(ROOT)} missing: run eval/claude_zeroshot.py test first, or pass --without-claude")
    if not args.probe and not args.without_probe:
        raise SystemExit("pass --probe runs/probes/<best> (see reports/probe_bakeoff.json) or --without-probe")
    print(f"artifact {mv}: T={T:.4f} tau={tau:.4f} beta={beta:g}; loading Predictor ...", file=sys.stderr)
    predictor = load_predictor(args.artifact)
    probe = Probe(args.probe, args.batch) if args.probe else None
    parity = parity_check(predictor, gp, beta, T, args.parity, args.batch)
    print(f"parity vs Predictor.probs on {parity['n_val_images']} val images: max diff {parity['max_abs_diff']:.1e}", file=sys.stderr)

    # ============================ test data is read from here ============================
    test = pd.read_csv(TEST_CSV, dtype={"service_request_id": str})
    idx = {l: i for i, l in enumerate(names)}
    labels = test["label"].map(idx).to_numpy()
    groups = test["group"].to_numpy()
    paths = [str(DATA / p) for p in test["path"]]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} test images missing (e.g. {missing[0]}); fetch the test split first")
    sub_ids = pd.read_csv(SUBSET_IDS, dtype={"service_request_id": str})["service_request_id"]
    pos = pd.Series(np.arange(len(test)), index=test["service_request_id"]).reindex(sub_ids).to_numpy()
    if np.isnan(pos).any():
        raise SystemExit("subset ids not all in the test split")
    pos = pos.astype(int)
    claude = None
    if not args.without_claude:
        cp = pd.read_csv(CLAUDE_PRED, dtype={"service_request_id": str}).set_index("service_request_id")
        if set(sub_ids) - set(cp.index):
            raise SystemExit("claude_baseline_predictions.csv does not cover every subset id")
        cp = cp.reindex(sub_ids)
        claude = np.array([idx.get(p, M.NO_ANSWER) if isinstance(p, str) and p else M.NO_ANSWER for p in cp["pred"]])
    print(f"test: {len(test)} images, {len(np.unique(groups))} groups, subset {len(pos)}", file=sys.stderr)

    if args.logits_cache and args.logits_cache.exists():
        logits = np.load(args.logits_cache)["logits"].astype(np.float64)
    else:
        logits = predict_logits(predictor, paths, args.batch)
        if args.logits_cache:
            np.savez(args.logits_cache, logits=logits.astype(np.float32), ids=test["service_request_id"].to_numpy().astype(str))
    assert logits.shape == (len(test), M.N_CLASSES)

    result: dict = {
        "model_version": mv, "git_sha": git_sha(), "when": datetime.now().isoformat(timespec="seconds"),
        "post_hoc": bool(args.post_hoc), "ledger_row": row, "n_test": int(len(test)), "temperature": T,
        "abstain_threshold": tau, "geo_prior_beta": beta, "parity_check": parity,
        "source": "data/test.csv (frozen; SPLIT_MANIFEST.json)",
    }
    L = gp.log_lift_batch(test["lat"].to_numpy(), test["long"].to_numpy()) if gp is not None else None
    if L is not None:
        result["geo_prior_cell_coverage"] = gp.coverage(test["lat"].to_numpy(), test["long"].to_numpy())
        result["with_geo_prior"] = M.summarize(fuse(logits, L, beta), labels, groups=groups, temperature=T, threshold=tau,
                                               prior=M.real_prior(), n_boot=args.n_boot, labels_names=names)
    ng = meta.get("val_metrics", {}).get("no_geo_prior") or {}
    T0, tau0 = float(ng.get("temperature") or T), float(ng.get("abstain_threshold") or tau)
    result["without_geo_prior"] = M.summarize(logits, labels, groups=groups, temperature=T0, threshold=tau0,
                                              prior=M.real_prior(), n_boot=args.n_boot, labels_names=names)
    result["without_geo_prior"]["note"] = ("image only; temperature/threshold from val_metrics.no_geo_prior"
                                           if ng else "image only; artifact temperature/threshold")
    result["headline"] = "with_geo_prior" if L is not None else "without_geo_prior"
    headline = result[result["headline"]]
    result["top_confusions"] = M.top_confusions(np.array(headline["confusion_matrix"]), names, k=5)

    # --- the 1,020-image subset: model vs Claude vs cascade vs frozen probe ----------------
    sub_logits = (fuse(logits, L, beta) if L is not None else logits)[pos]
    sub_labels, sub_groups = labels[pos], groups[pos]
    probs = M.softmax(sub_logits, T)
    model_pred = probs.argmax(1)
    abstain = probs.max(1) < tau
    subset: dict = {"n": int(len(pos)), "ids_file": str(SUBSET_IDS.relative_to(ROOT)), "chance_top1": 1 / M.N_CLASSES}
    s = M.summarize(sub_logits, sub_labels, groups=sub_groups, temperature=T, threshold=tau, n_boot=args.n_boot, labels_names=names)
    for k in ("per_class", "confusion_matrix"):
        s.pop(k, None)
    subset["model"] = s | {"abstain_rate": float(abstain.mean())}

    def na_block(pred: np.ndarray) -> dict:
        return {"top1": M.top1_na(pred, sub_labels), "macro_f1": M.macro_f1_na(pred, sub_labels),
                "n_no_answer": int((pred < 0).sum()),
                "ci95": {"top1": list(M.cluster_bootstrap_ci(lambda i: M.top1_na(pred[i], sub_labels[i]), sub_groups, args.n_boot)),
                         "macro_f1": list(M.cluster_bootstrap_ci(lambda i: M.macro_f1_na(pred[i], sub_labels[i]), sub_groups, args.n_boot))}}

    if claude is not None:
        subset["claude_zeroshot"] = na_block(claude) | {"source": str(CLAUDE_PRED.relative_to(ROOT))}
        cascade = np.where(abstain, claude, model_pred)
        subset["cascade_model_then_claude_on_abstain"] = na_block(cascade) | {"claude_used_rate": float(abstain.mean())}
    else:
        subset["claude_zeroshot"] = {"skipped": "--without-claude"}
    if probe is not None:
        pl = probe.logits([paths[i] for i in pos])
        sp = M.summarize(pl, sub_labels, groups=sub_groups, temperature=1.0, n_boot=args.n_boot, labels_names=names)
        for k in ("per_class", "confusion_matrix"):
            sp.pop(k, None)
        subset["best_frozen_probe"] = sp | {"probe": probe.name, "head": str(args.probe)}
    else:
        subset["best_frozen_probe"] = {"skipped": "--without-probe"}
    result["subset_1020"] = subset

    REPORTS.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    confusion_png(np.array(headline["confusion_matrix"]), names,
                  REPORTS / ("confusion_matrix_posthoc.png" if args.post_hoc else "confusion_matrix.png"),
                  f"{mv} (test, {result['headline']}, T={T:.2f})")
    h, sel = headline, headline["selective"]
    print(f"\n{mv} on test (n={len(test)}), {result['headline']}:")
    print(f"  top-1 {h['top1']:.4f} [{h['ci95']['top1'][0]:.4f}, {h['ci95']['top1'][1]:.4f}]   top-3 {h['top3']:.4f}")
    print(f"  macro-F1 {h['macro_f1']:.4f} [{h['ci95']['macro_f1'][0]:.4f}, {h['ci95']['macro_f1'][1]:.4f}]   ECE {h['ece']:.4f}   AURC {h['aurc']:.4f}")
    print(f"  at tau={tau:.3f}: coverage {sel['coverage']:.1%} [{h['ci95']['coverage'][0]:.1%}, {h['ci95']['coverage'][1]:.1%}], "
          f"selective acc {sel['selective_accuracy']:.4f} (lower-95% {sel['selective_accuracy_lower95']:.4f})")
    if L is not None:
        w = result["without_geo_prior"]
        print(f"  without geo-prior: top-1 {w['top1']:.4f}  macro-F1 {w['macro_f1']:.4f}")
    if claude is not None:
        print(f"  subset n={subset['n']}: model {subset['model']['top1']:.4f} | Claude zero-shot {subset['claude_zeroshot']['top1']:.4f} "
              f"| cascade {subset['cascade_model_then_claude_on_abstain']['top1']:.4f}"
              + (f" | probe {subset['best_frozen_probe']['top1']:.4f}" if probe is not None else ""))
    print(f"  wrote {out.relative_to(ROOT)} and reports/confusion_matrix{'_posthoc' if args.post_hoc else ''}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
