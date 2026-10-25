"""Inference library: the A -> B interface in contracts/predictor.md.

    from ml.infer import Predictor
    p = Predictor.from_artifact("artifacts/<model_version>")
    p.logits(paths)            # (N, 17) raw logits (1 member) or log of averaged member probs (ensemble)
    p.probs(paths, latlng)     # calibrated: optional geo-prior, then temperature

Takes image paths only and never reads a split CSV, so test paths can only come from
B's eval/final_eval.py. Preprocessing comes from model_meta.json, per member.
"""
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T

from ml.data import CoverCrop, pick_device


class Predictor:
    def __init__(self, meta, members, device):
        self.meta = meta
        self.members = members  # list of (model, transform)
        self.device = device

    @classmethod
    def from_artifact(cls, artifact_dir, device=None):
        import timm

        artifact_dir = Path(artifact_dir)
        meta = json.loads((artifact_dir / "model_meta.json").read_text())
        device = torch.device(device) if device else pick_device()
        members = []
        for m in meta["members"]:
            model = timm.create_model(m["timm_name"], pretrained=False, num_classes=len(meta["classes"]),
                                      **m["timm_kwargs"])
            model.load_state_dict(torch.load(artifact_dir / m["file"], map_location="cpu", weights_only=True))
            model.eval().to(device)
            w, h = m["input_wh"]
            transform = T.Compose([CoverCrop(w, h), T.ToTensor(), T.Normalize(m["mean"], m["std"])])
            members.append((model, transform))
        return cls(meta, members, device)

    @staticmethod
    def _open(item):
        """A path (eval) or an already-decoded PIL image (the API receives bytes, not files)."""
        return item.convert("RGB") if isinstance(item, Image.Image) else Image.open(item).convert("RGB")

    @torch.no_grad()
    def _member_logits(self, model, transform, paths, batch):
        out = []
        for i in range(0, len(paths), batch):
            x = torch.stack([transform(self._open(p)) for p in paths[i:i + batch]]).to(self.device)
            with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
                z = model(x)
            if self.meta.get("tta_hflip"):
                with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
                    z = (z.float() + model(torch.flip(x, dims=[3])).float()) / 2
            out.append(z.float().cpu())
        return torch.cat(out)

    def logits(self, paths, batch=64):
        paths = [p if isinstance(p, Image.Image) else str(p) for p in paths]
        if len(self.members) == 1:
            model, transform = self.members[0]
            return self._member_logits(model, transform, paths, batch).numpy()
        probs = torch.stack([self._member_logits(m, t, paths, batch).softmax(-1) for m, t in self.members]).mean(0)
        return probs.clamp_min(1e-12).log().numpy()

    def calibration(self, with_location):
        """(temperature, abstain_threshold) for this request. With the geo-prior on (beta > 0) but no
        location, use the prior-free calibration B saves under val_metrics.no_geo_prior."""
        beta = self.meta.get("geo_prior_beta") or 0.0
        if beta and not with_location:
            no_geo = (self.meta.get("val_metrics") or {}).get("no_geo_prior") or {}
            if no_geo.get("temperature"):
                return no_geo["temperature"], no_geo.get("abstain_threshold")
        return self.meta.get("temperature") or 1.0, self.meta.get("abstain_threshold")

    def probs(self, paths, latlng=None, batch=64):
        z = torch.from_numpy(self.logits(paths, batch))
        beta = self.meta.get("geo_prior_beta") or 0.0
        if beta and latlng is not None:
            from ml.geoprior import log_lift

            z = z + beta * torch.from_numpy(np.stack([log_lift(lat, lng) for lat, lng in latlng])).float()
        temperature, _ = self.calibration(with_location=latlng is not None)
        return (z / temperature).softmax(-1).numpy()
