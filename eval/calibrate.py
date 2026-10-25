"""B2b + B2d: calibrate the final model or ensemble on val and write the result into the artifact.

  python eval/calibrate.py --artifact artifacts/<v> --val-logits runs/<m0>/val_logits.npz [runs/<m1>/... ]
      [--geoprior artifacts/geoprior/geoprior.npz] [--beta-grid 0,0.25,0.5,0.75,1.0,1.5]
      [--target 0.90] [--n-boot 1000]

One val_logits.npz per member of model_meta.json `members`, in the same order. The members
are combined exactly as `ml/infer.py` does (average softmax probabilities, log of the average,
contracts/predictor.md), then:
  1. (optional) beta for the geo-prior is chosen on val: macro-F1, AURC as the tie-breaker,
     over --beta-grid. beta = 0 means off.
  2. the temperature is fitted (one scalar, min NLL) AFTER fusion,
  3. abstain_threshold = smallest max-prob whose Clopper-Pearson lower-95% bound on val
     selective accuracy is >= --target (PLAN 3.5).
Writes `temperature`, `abstain_threshold`, `val_metrics` into artifacts/<v>/model_meta.json
(validated against contracts/model_meta.schema.json) and the full bundle to reports/val_metrics.json.

Reads data/val.csv only. Never the test split.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import metrics as M  # noqa: E402
from eval.val_report import load_run, load_val  # noqa: E402

SCHEMA = ROOT / "contracts" / "model_meta.schema.json"


def validate_meta(meta: dict) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return []
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema).iter_errors(meta)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--val-logits", nargs="+", type=Path, required=True, help="one per member, same order")
    ap.add_argument("--geoprior", type=Path, help="A's geoprior.npz; tunes beta on val when given")
    ap.add_argument("--beta-grid", default="0,0.25,0.5,0.75,1.0,1.5")
    ap.add_argument("--target", type=float, default=0.90)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "val_metrics.json")
    ap.add_argument("--force", action="store_true", help="allow member count != number of logits files")
    args = ap.parse_args()

    meta_path = args.artifact / "model_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    names = M.class_labels()
    if meta["classes"] != names:
        raise SystemExit("model_meta.classes != contracts/categories.json label order")
    if len(meta["members"]) != len(args.val_logits) and not args.force:
        raise SystemExit(f"{len(meta['members'])} members but {len(args.val_logits)} logits files (use --force to override)")

    val = load_val()
    labels = val["label_idx"].to_numpy()
    groups = val["group"].to_numpy()
    members = [load_run(p, val) for p in args.val_logits]
    logits = members[0][2] if len(members) == 1 else M.ensemble_logits([m[2] for m in members])

    # --- B2d: geo-prior beta on val -------------------------------------------------------
    beta, beta_table, cell_cov = 0.0, [], None
    L = None
    if args.geoprior:
        from eval.geo import GeoPrior, fuse
        gp = GeoPrior(args.geoprior)
        L = gp.log_lift_batch(val["lat"].to_numpy(), val["long"].to_numpy())
        cell_cov = gp.coverage(val["lat"].to_numpy(), val["long"].to_numpy())
        for b in [float(x) for x in args.beta_grid.split(",")]:
            fz = fuse(logits, L, b)
            T_b = M.fit_temperature(fz, labels)
            p = M.softmax(fz, T_b)
            beta_table.append({"beta": b, "macro_f1": M.macro_f1(p.argmax(1), labels), "top1": M.top_k_accuracy(p, labels, 1),
                               "aurc": M.aurc(p, labels), "temperature": T_b, "nll": M.nll(fz, labels, T_b)})
        best = sorted(beta_table, key=lambda r: (-round(r["macro_f1"], 6), r["aurc"]))[0]
        beta = best["beta"]
        print("beta sweep (val):", file=sys.stderr)
        for r in beta_table:
            print(f"  beta={r['beta']:<5g} macro-F1={r['macro_f1']:.4f} top-1={r['top1']:.4f} AURC={r['aurc']:.4f}"
                  f"{'  <- chosen' if r is best else ''}", file=sys.stderr)
        logits = fuse(logits, L, beta)

    # --- temperature after fusion, then the threshold ---------------------------------------
    T = M.fit_temperature(logits, labels)
    probs = M.softmax(logits, T)
    rule = M.abstain_threshold(probs, labels, target=args.target)
    tau = rule["threshold"]
    s = M.summarize(logits, labels, groups=groups, temperature=T, threshold=tau, prior=M.real_prior(),
                    n_boot=args.n_boot, labels_names=names)
    s.update({
        "model_version": meta["model_version"],
        "members": [{"run": m[0], "timm_name": m[1], "file": str(p)} for m, p in zip(members, args.val_logits)],
        "abstain_rule": rule,
        "geo_prior": {"beta": beta, "file": str(args.geoprior) if args.geoprior else None,
                      "val_cell_coverage": cell_cov, "sweep": beta_table},
        "source": "data/val.csv",
    })
    if L is not None:
        s["without_geo_prior"] = M.summarize(logits - beta * L, labels, temperature=M.fit_temperature(logits - beta * L, labels),
                                             labels_names=names) | {"note": "same members, beta=0, own temperature"}
        s["without_geo_prior"].pop("confusion_matrix", None)
        s["without_geo_prior"].pop("per_class", None)

    sel = s["selective"]
    meta["temperature"] = round(T, 6)
    meta["abstain_threshold"] = round(tau, 6)
    meta["val_metrics"] = {
        "top1": round(s["top1"], 6), "top3": round(s["top3"], 6), "macro_f1": round(s["macro_f1"], 6),
        "ece": round(s["ece"], 6), "aurc": round(s["aurc"], 6),
        "coverage_at_threshold": round(sel["coverage"], 6), "acc_at_threshold": round(sel["selective_accuracy"], 6),
        "acc_at_threshold_lower95": round(sel["selective_accuracy_lower95"], 6),
        "geo_prior_beta": beta, "calibrated_on": "data/val.csv", "n_val": int(len(labels)),
    }
    schema_props = json.loads(SCHEMA.read_text(encoding="utf-8")).get("properties", {})
    if "geo_prior_beta" in schema_props:
        meta["geo_prior_beta"] = beta
    elif args.geoprior:
        print("NOTE: contracts/model_meta.schema.json has no `geo_prior_beta` yet; wrote it under val_metrics. "
              "A6's shared PR should add the top-level field; ml/infer.py can read either.", file=sys.stderr)
    errors = validate_meta(meta)
    if errors:
        raise SystemExit("model_meta.json would not validate:\n  " + "\n  ".join(errors))
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")

    ci = s["ci95"]
    print(f"\n{meta['model_version']}  (val n={len(labels)}, {s['n_groups']} groups)")
    print(f"  temperature        {T:.4f}   ECE {s['ece_uncalibrated']:.4f} -> {s['ece']:.4f}")
    print(f"  geo-prior beta     {beta:g}" + (f"   (cells covered: {cell_cov:.1%})" if cell_cov is not None else ""))
    print(f"  macro-F1           {s['macro_f1']:.4f}  [{ci['macro_f1'][0]:.4f}, {ci['macro_f1'][1]:.4f}]")
    print(f"  top-1 / top-3      {s['top1']:.4f} / {s['top3']:.4f}")
    print(f"  AURC               {s['aurc']:.4f}  [{ci['aurc'][0]:.4f}, {ci['aurc'][1]:.4f}]")
    print(f"  abstain threshold  {tau:.4f}  -> coverage {sel['coverage']:.1%}, selective acc {sel['selective_accuracy']:.4f} "
          f"(lower-95% {sel['selective_accuracy_lower95']:.4f} >= {args.target})")
    print(f"  wrote {meta_path} and {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
