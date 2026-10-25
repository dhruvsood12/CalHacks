"""Datasets, backbones and transforms shared by every ml/ script.

Rules enforced here (PLAN §3.4, §4):
  - The test split is refused; only eval/final_eval.py (B's lane) reads it.
  - Items are (image_tensor, label_index): pixels only, no metadata.
  - Every image is cropped to one fixed shape per crop mode. Never padded or
    squashed, so the aspect-ratio shortcut (square illegal_posting photos) is closed.
"""
import csv
import json
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms as T

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CLASSES = [c["label"] for c in json.loads((ROOT / "contracts" / "categories.json").read_text())["classes"]]
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}

BACKBONES = {
    "siglip2": {"timm_name": "vit_base_patch16_siglip_384.v2_webli", "kwargs": {}, "size": 384, "stride": 16},
    "dinov2": {"timm_name": "vit_base_patch14_dinov2.lvd142m", "kwargs": {"img_size": 378}, "size": 378, "stride": 14},
    "convnext": {"timm_name": "convnext_base.fb_in22k_ft_in1k_384", "kwargs": {}, "size": 384, "stride": 32},
}
CROP_MODES = ("square", "portrait34")


def output_size(backbone, crop_mode):
    """(width, height) fed to the network. portrait34 keeps the whole frame of 3:4 portrait photos."""
    b = BACKBONES[backbone]
    w = b["size"]
    if crop_mode == "square":
        return w, w
    if crop_mode == "portrait34":
        h = round(w * 4 / 3 / b["stride"]) * b["stride"]
        return w, h
    raise ValueError(f"unknown crop mode {crop_mode!r}")


def create_model(backbone, crop_mode, num_classes=0, pretrained=True):
    import timm

    b = BACKBONES[backbone]
    kwargs = dict(b["kwargs"])
    if crop_mode != "square" and backbone != "convnext":
        kwargs["dynamic_img_size"] = True  # ViT position embeddings interpolated to the 3:4 grid
    return timm.create_model(b["timm_name"], pretrained=pretrained, num_classes=num_classes, **kwargs)


def norm_stats(model):
    import timm

    cfg = timm.data.resolve_model_data_config(model)
    return list(cfg["mean"]), list(cfg["std"])


def cover_crop(img, out_w, out_h):
    """Resize so the image covers (out_w, out_h), then center-crop. No padding, no squash."""
    w, h = img.size
    s = max(out_w / w, out_h / h)
    nw, nh = max(out_w, round(w * s)), max(out_h, round(h * s))
    img = img.resize((nw, nh), Image.BICUBIC)
    left, top = (nw - out_w) // 2, (nh - out_h) // 2
    return img.crop((left, top, left + out_w, top + out_h))


class CoverCrop:
    """Picklable wrapper (DataLoader workers on macOS spawn and can't pickle lambdas)."""

    def __init__(self, out_w, out_h):
        self.out_w, self.out_h = out_w, out_h

    def __call__(self, img):
        return cover_crop(img, self.out_w, self.out_h)


def eval_transform(out_w, out_h, mean, std):
    return T.Compose([
        CoverCrop(out_w, out_h),
        T.ToTensor(),
        T.Normalize(mean, std),
    ])


def train_transform(out_w, out_h, mean, std):
    aspect = out_w / out_h
    return T.Compose([
        T.RandomResizedCrop((out_h, out_w), scale=(0.5, 1.0), ratio=(aspect * 3 / 4, aspect * 4 / 3),
                            interpolation=T.InterpolationMode.BICUBIC),
        T.RandomHorizontalFlip(),
        T.ColorJitter(0.2, 0.2, 0.2),
        T.RandomRotation(10, interpolation=T.InterpolationMode.BILINEAR),
        T.ToTensor(),
        T.Normalize(mean, std),
    ])


def read_split(name):
    """Rows of data/<name>.csv for name in {'train', 'val'}. Test is sealed (CLAUDE.md rule 3)."""
    if name not in ("train", "val"):
        raise PermissionError(f"ml/ may only read train or val, not {name!r}")
    return list(csv.DictReader(open(DATA / f"{name}.csv")))


class SplitDataset(Dataset):
    def __init__(self, rows, transform):
        self.rows = rows
        self.transform = transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        img = Image.open(DATA / r["path"]).convert("RGB")
        return self.transform(img), CLASS_INDEX[r["label"]]


def pick_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
