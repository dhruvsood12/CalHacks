"""LP-FT fine-tuning of one backbone (PLAN §3.4).

The head starts from the frozen linear probe (runs/probes/<backbone>-<crop>/head.npz),
then every layer trains with layer-wise LR decay. Every epoch is scored on val; the
best val macro-F1 checkpoint is kept and its val logits are written for B
(contracts/predictor.md). Never reads test.

Usage:
  python -m ml.train --backbone siglip2 --crop-mode square --recipe default --seed 13
  python -m ml.train ... --limit 256 --epochs 1          # smoke test
Output: runs/<backbone>-<crop>-lpft-<recipe>-s<seed>/{config.json, metrics.jsonl, best.pt, val_logits.npz}
"""
import argparse
import json
import math
import random
import subprocess
import time

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader

from ml.data import (BACKBONES, CLASS_INDEX, CLASSES, CROP_MODES, ROOT, SplitDataset, create_model,
                     eval_transform, norm_stats, output_size, pick_device, read_split, train_transform)

RECIPES = {
    "default": {"top_lr": 5e-5, "head_lr": 1e-3, "layer_decay": 0.75, "label_smoothing": 0.1},
    "alt": {"top_lr": 1e-4, "head_lr": 1e-3, "layer_decay": 0.65, "label_smoothing": 0.0},
}


def param_groups(model, top_lr, head_lr, layer_decay, weight_decay):
    """Layer-wise LR decay for the backbone (top block gets top_lr), a separate LR for the head."""
    from timm.optim import param_groups_layer_decay

    head_ids = {id(p) for p in model.get_classifier().parameters()}
    groups = param_groups_layer_decay(model, weight_decay=weight_decay, layer_decay=layer_decay)
    # timm counts every ConvNeXt block as a layer (~38), so a per-layer decay tuned for a
    # 12-block ViT would all but freeze its early stages. Rescale to a 12-layer-equivalent span.
    n_layers = len({g["lr_scale"] for g in groups}) - 1
    if n_layers > 14:
        groups = param_groups_layer_decay(model, weight_decay=weight_decay,
                                          layer_decay=layer_decay ** (12 / n_layers))
    backbone_scales = [g["lr_scale"] for g in groups if any(id(p) not in head_ids for p in g["params"])]
    top = max(s for s in backbone_scales if s < 1.0) if any(s < 1.0 for s in backbone_scales) else 1.0
    out, head_params = [], []
    for g in groups:
        body = [p for p in g["params"] if id(p) not in head_ids]
        head_params += [p for p in g["params"] if id(p) in head_ids]
        if body:
            out.append({"params": body, "weight_decay": g["weight_decay"],
                        "lr": top_lr * min(g["lr_scale"] / top, 1.0)})
    out.append({"params": head_params, "weight_decay": weight_decay, "lr": head_lr})
    return out


def init_head_from_probe(model, backbone, crop_mode):
    path = ROOT / "runs" / "probes" / f"{backbone}-{crop_mode}" / "head.npz"
    if not path.exists():
        print(f"WARNING: no probe head at {path}; head starts random (plain fine-tuning, not LP-FT)")
        return False
    h = np.load(path)
    head = model.get_classifier()
    with torch.no_grad():
        head.weight.copy_(torch.from_numpy(h["weight"]))
        head.bias.copy_(torch.from_numpy(h["bias"]))
    return True


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    logits, labels = [], []
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits.append(model(x).float().cpu())
        labels.append(y)
    logits, labels = torch.cat(logits).numpy(), torch.cat(labels).numpy()
    rank = np.argsort(-logits, axis=1)
    return logits, labels, {
        "val_top1": float((rank[:, 0] == labels).mean()),
        "val_top3": float(np.mean([labels[i] in rank[i, :3] for i in range(len(labels))])),
        "val_macro_f1": float(f1_score(labels, rank[:, 0], average="macro")),
        "val_nll": float(F.cross_entropy(torch.from_numpy(logits), torch.from_numpy(labels)).item()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backbone", choices=sorted(BACKBONES), required=True)
    ap.add_argument("--crop-mode", choices=CROP_MODES, required=True)
    ap.add_argument("--recipe", choices=sorted(RECIPES), default="default")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--accum", type=int, default=1, help="gradient accumulation steps (effective batch = batch*accum)")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--weight-decay", type=float, default=0.05)
    ap.add_argument("--grad-checkpointing", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N rows per split (smoke test only)")
    args = ap.parse_args()
    recipe = RECIPES[args.recipe]

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = pick_device()
    run = f"{args.backbone}-{args.crop_mode}-lpft-{args.recipe}-s{args.seed}" + ("-smoke" if args.limit else "")
    out = ROOT / "runs" / run
    out.mkdir(parents=True, exist_ok=True)

    model = create_model(args.backbone, args.crop_mode, num_classes=len(CLASSES))
    lp_init = init_head_from_probe(model, args.backbone, args.crop_mode)
    if args.grad_checkpointing:
        model.set_grad_checkpointing(True)
    model.to(device)
    mean, std = norm_stats(model)
    out_w, out_h = output_size(args.backbone, args.crop_mode)

    tr_rows, va_rows = read_split("train"), read_split("val")
    if args.limit:
        tr_rows, va_rows = tr_rows[:args.limit], va_rows[:args.limit]
    train_loader = DataLoader(SplitDataset(tr_rows, train_transform(out_w, out_h, mean, std)),
                              batch_size=args.batch, shuffle=True, drop_last=True, num_workers=args.workers,
                              pin_memory=device.type == "cuda", persistent_workers=args.workers > 0)
    val_loader = DataLoader(SplitDataset(va_rows, eval_transform(out_w, out_h, mean, std)),
                            batch_size=args.batch, num_workers=args.workers,
                            pin_memory=device.type == "cuda", persistent_workers=args.workers > 0)

    groups = param_groups(model, recipe["top_lr"], recipe["head_lr"], recipe["layer_decay"], args.weight_decay)
    opt = torch.optim.AdamW(groups, betas=(0.9, 0.999))
    steps_per_epoch = max(1, len(train_loader) // args.accum)
    total, warmup = steps_per_epoch * args.epochs, steps_per_epoch
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warmup if s < warmup else 0.5 * (1 + math.cos(math.pi * (s - warmup) / max(1, total - warmup))))

    config = {**vars(args), **recipe, "run": run, "timm_name": BACKBONES[args.backbone]["timm_name"],
              "timm_kwargs": BACKBONES[args.backbone]["kwargs"], "input_wh": [out_w, out_h], "mean": mean,
              "std": std, "lp_init": lp_init, "device": str(device),
              "gpu": torch.cuda.get_device_name() if device.type == "cuda" else None,
              "git_sha": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                        text=True).stdout.strip(),
              "n_train": len(tr_rows), "n_val": len(va_rows)}
    (out / "config.json").write_text(json.dumps(config, indent=2))
    log = open(out / "metrics.jsonl", "a")

    best_f1, step = -1.0, 0
    for epoch in range(args.epochs):
        model.train()
        t0, seen, loss_sum = time.time(), 0, 0.0
        opt.zero_grad(set_to_none=True)
        for i, (x, y) in enumerate(train_loader):
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                loss = F.cross_entropy(model(x), y, label_smoothing=recipe["label_smoothing"]) / args.accum
            loss.backward()
            if (i + 1) % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
            seen += len(y)
            loss_sum += loss.item() * args.accum * len(y)
        train_sec = time.time() - t0
        logits, labels, m = evaluate(model, val_loader, device)
        rec = {"epoch": epoch + 1, "train_loss": loss_sum / max(seen, 1), "train_img_per_sec": seen / train_sec,
               "epoch_sec": round(time.time() - t0, 1), **m}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)
        if m["val_macro_f1"] > best_f1:
            best_f1 = m["val_macro_f1"]
            torch.save(model.state_dict(), out / "best.pt")
            np.savez(out / "val_logits.npz", ids=np.array([r["service_request_id"] for r in va_rows]),
                     logits=logits.astype(np.float32), labels=labels, run=run, timm_name=config["timm_name"])
            (out / "best.json").write_text(json.dumps({**rec, "run": run}, indent=2))
    print(f"DONE {run} best val macro-F1 {best_f1:.4f}", flush=True)


if __name__ == "__main__":
    main()
