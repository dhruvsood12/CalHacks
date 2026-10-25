"""Package one or more finished runs into an artifact B can calibrate and A can serve.

Usage: python -m ml.export --runs siglip2-square-lpft-default-s13 [more runs ...] [--version NAME]
Output: artifacts/<version>/{model_meta.json, member_0.pt, ...}
temperature / abstain_threshold / val_metrics stay empty: B fills them on val (eval/calibrate.py).
"""
import argparse
import json
import shutil
import subprocess

from ml.data import CLASSES, ROOT


def member_entry(run_dir, index):
    cfg = json.loads((run_dir / "config.json").read_text())
    w, h = cfg["input_wh"]
    kwargs = dict(cfg["timm_kwargs"])
    if w != h and "convnext" not in cfg["timm_name"]:
        kwargs["dynamic_img_size"] = True
    return {"file": f"member_{index}.pt", "timm_name": cfg["timm_name"], "timm_kwargs": kwargs,
            "img_size": w, "input_wh": [w, h], "crop_mode": cfg["crop_mode"],
            "mean": cfg["mean"], "std": cfg["std"], "run": cfg["run"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--version")
    args = ap.parse_args()
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    version = args.version or ("ens-" if len(args.runs) > 1 else "") + "+".join(args.runs) + f"-{sha}"
    out = ROOT / "artifacts" / version
    out.mkdir(parents=True, exist_ok=True)
    members = []
    for i, run in enumerate(args.runs):
        run_dir = ROOT / "runs" / run
        shutil.copy(run_dir / "best.pt", out / f"member_{i}.pt")
        members.append(member_entry(run_dir, i))
    meta = {"model_version": version, "classes": CLASSES, "members": members, "temperature": None,
            "abstain_threshold": None, "val_metrics": {}, "train_git_sha": sha,
            "split_manifest_sha256": json.loads((ROOT / "data" / "SPLIT_MANIFEST.json").read_text())["files"]}
    try:
        from jsonschema import Draft202012Validator

        schema = json.loads((ROOT / "contracts" / "model_meta.schema.json").read_text())
        errors = [e.message for e in Draft202012Validator(schema).iter_errors(meta)]
        if errors:
            raise SystemExit(f"model_meta.json does not match contracts/model_meta.schema.json: {errors}")
    except ImportError:
        print("WARNING: jsonschema missing; schema not checked")
    (out / "model_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"exported {out}")


if __name__ == "__main__":
    main()
