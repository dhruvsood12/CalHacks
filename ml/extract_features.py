"""Frozen backbone features for train and val (the linear-probe baseline, PLAN §3.3).

Usage: python -m ml.extract_features --backbone siglip2 --crop-mode square
Output: runs/features/<backbone>-<crop_mode>/{train,val}.npz  (ids, feats, labels)
"""
import argparse
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from ml.data import (BACKBONES, CLASS_INDEX, CROP_MODES, ROOT, SplitDataset, create_model, eval_transform,
                     norm_stats, output_size, pick_device, read_split)


@torch.inference_mode()
def extract(model, rows, transform, device, batch, workers):
    loader = DataLoader(SplitDataset(rows, transform), batch_size=batch, num_workers=workers,
                        pin_memory=device.type == "cuda", persistent_workers=workers > 0)
    feats = []
    for x, _ in loader:
        x = x.to(device, non_blocking=True)
        if device.type == "cuda":
            with torch.autocast("cuda", dtype=torch.bfloat16):
                f = model(x)
        elif device.type == "mps":
            f = model(x.half())  # fp16 doubles Apple-GPU throughput; features are cast back to fp32
        else:
            f = model(x)
        feats.append(f.float().cpu().numpy())
    return np.concatenate(feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backbone", choices=sorted(BACKBONES), required=True)
    ap.add_argument("--crop-mode", choices=CROP_MODES, required=True)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="first N rows per split (smoke test only)")
    args = ap.parse_args()

    device = pick_device()
    model = create_model(args.backbone, args.crop_mode).eval().to(device)
    if device.type == "mps":
        model = model.half()
    mean, std = norm_stats(model)
    out_w, out_h = output_size(args.backbone, args.crop_mode)
    transform = eval_transform(out_w, out_h, mean, std)
    out_dir = ROOT / "runs" / "features" / f"{args.backbone}-{args.crop_mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for split in ("train", "val"):
        rows = read_split(split)
        if args.limit:
            rows = rows[:args.limit]
        t0 = time.time()
        feats = extract(model, rows, transform, device, args.batch, args.workers)
        secs = time.time() - t0
        np.savez(out_dir / f"{split}.npz",
                 ids=np.array([r["service_request_id"] for r in rows]),
                 feats=feats.astype(np.float32),
                 labels=np.array([CLASS_INDEX[r["label"]] for r in rows], dtype=np.int64),
                 timm_name=BACKBONES[args.backbone]["timm_name"], crop_mode=args.crop_mode,
                 out_w=out_w, out_h=out_h, mean=np.array(mean), std=np.array(std), seconds=secs,
                 device=str(device), precision={"cuda": "bf16", "mps": "fp16"}.get(device.type, "fp32"))
        print(f"{args.backbone}-{args.crop_mode} {split}: {feats.shape} in {secs:.0f}s "
              f"({len(rows) / secs:.1f} img/s on {device})", flush=True)


if __name__ == "__main__":
    main()
