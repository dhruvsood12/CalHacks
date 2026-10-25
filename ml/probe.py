"""Linear probes on frozen features: the baseline, the crop-mode check and the LP-FT head init.

For each runs/features/<backbone>-<mode>/ it fits multinomial logistic regression on
standardized train features (L-BFGS, L2 strength chosen on val) and writes:
  runs/probes/<backbone>-<mode>/head.npz        weights folded back to raw-feature space
  runs/probes/<backbone>-<mode>/val_logits.npz  contracts/predictor.md format, for B
  reports/probe_bakeoff.json                    val metrics per backbone x crop mode

Usage: python -m ml.probe [--only siglip2-square ...]
"""
import argparse
import json
import subprocess
import time

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import f1_score

from ml.data import CLASSES, ROOT

C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0)


def fit(x, y, c, n_classes):
    """Minimize mean cross-entropy + ||W||^2 / (2 C n); same objective as sklearn's C."""
    w = torch.zeros(x.shape[1], n_classes, dtype=torch.float64, requires_grad=True)
    b = torch.zeros(n_classes, dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([w, b], lr=1, max_iter=500, history_size=20, tolerance_grad=1e-6,
                            line_search_fn="strong_wolfe")
    reg = 1.0 / (2 * c * len(y))

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(x @ w + b, y) + reg * (w * w).sum()
        loss.backward()
        return loss

    opt.step(closure)
    return w.detach(), b.detach()


def metrics(logits, y):
    rank = np.argsort(-logits, axis=1)
    return {"val_top1": float((rank[:, 0] == y).mean()),
            "val_top3": float(np.mean([y[i] in rank[i, :3] for i in range(len(y))])),
            "val_macro_f1": float(f1_score(y, rank[:, 0], average="macro"))}


def run_one(feat_dir):
    tr, va = np.load(feat_dir / "train.npz"), np.load(feat_dir / "val.npz")
    mu, sd = tr["feats"].mean(0), tr["feats"].std(0) + 1e-6
    xt = torch.from_numpy((tr["feats"] - mu) / sd).double()
    xv = torch.from_numpy((va["feats"] - mu) / sd).double()
    yt = torch.from_numpy(tr["labels"])
    yv = va["labels"]
    best, sweep = None, {}
    for c in C_GRID:
        t0 = time.time()
        w, b = fit(xt, yt, c, len(CLASSES))
        logits = (xv @ w + b).numpy()
        m = metrics(logits, yv)
        sweep[str(c)] = {**m, "fit_sec": round(time.time() - t0, 1)}
        if best is None or m["val_macro_f1"] > best[0]["val_macro_f1"]:
            best = (m, c, w.numpy(), b.numpy(), logits)
    m, c, w, b, logits = best
    w_raw = w / sd[:, None]
    b_raw = b - (mu / sd) @ w
    out = ROOT / "runs" / "probes" / feat_dir.name
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / "head.npz", weight=w_raw.T.astype(np.float32), bias=b_raw.astype(np.float32), C=c,
             timm_name=str(tr["timm_name"]), crop_mode=str(tr["crop_mode"]))
    np.savez(out / "val_logits.npz", ids=va["ids"], logits=logits.astype(np.float32), labels=yv,
             run=f"probe-{feat_dir.name}", timm_name=str(tr["timm_name"]))
    return {**m, "C": c, "feat_dim": int(tr["feats"].shape[1]), "timm_name": str(tr["timm_name"]),
            "crop_mode": str(tr["crop_mode"]), "input_wh": [int(tr["out_w"]), int(tr["out_h"])],
            "extract_sec": {"train": round(float(tr["seconds"]), 1), "val": round(float(va["seconds"]), 1)},
            "device": str(tr["device"]), "n_train": int(len(yt)), "n_val": int(len(yv)), "c_sweep": sweep}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    feat_root = ROOT / "runs" / "features"
    dirs = sorted(d for d in feat_root.iterdir() if (d / "val.npz").exists())
    if args.only:
        dirs = [d for d in dirs if d.name in args.only]
    report_path = ROOT / "reports" / "probe_bakeoff.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {"runs": {}}
    for d in dirs:
        report["runs"][d.name] = run_one(d)
        r = report["runs"][d.name]
        print(f"{d.name:22s} top1={r['val_top1']:.3f} top3={r['val_top3']:.3f} "
              f"macroF1={r['val_macro_f1']:.3f} C={r['C']}", flush=True)
    chosen = {}
    for name, r in report["runs"].items():
        bb = name.rsplit("-", 1)[0]
        if bb not in chosen or r["val_macro_f1"] > report["runs"][chosen[bb]]["val_macro_f1"]:
            chosen[bb] = name
    report["chosen_crop_mode"] = {bb: report["runs"][n]["crop_mode"] for bb, n in sorted(chosen.items())}
    report["note"] = ("Frozen-feature linear probes; L2 strength and crop mode chosen on val. "
                      "These are the baseline the fine-tuned models must beat; test is not used here.")
    report["git_sha"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       capture_output=True, text=True).stdout.strip()
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print("chosen crop mode:", report["chosen_crop_mode"])


if __name__ == "__main__":
    main()
