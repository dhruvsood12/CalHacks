"""Classifiers behind POST /classify (contracts/classify.response.schema.json).

CLASSIFIER=stub   deterministic fake from the image hash (works before any model exists)
CLASSIFIER=model  ml.infer.Predictor on MODEL_ARTIFACT_DIR (temperature, abstain threshold and
                  geo-prior beta come from the artifact's model_meta.json, set by B on val)
"""
import hashlib
import io
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = json.loads((ROOT / "contracts" / "categories.json").read_text())["classes"]
LABELS = [c["label"] for c in CATEGORIES]
BY_LABEL = {c["label"]: c for c in CATEGORIES}
UNCALIBRATED_THRESHOLD = 0.5  # used only until B's calibration fills abstain_threshold


def _response(probs, threshold, model_version, used_location, t0):
    order = np.argsort(-probs)[:3]
    top_k = [{"label": LABELS[i], "display_name": BY_LABEL[LABELS[i]]["display_name"],
              "agency": BY_LABEL[LABELS[i]]["primary_agency"], "prob": round(float(probs[i]), 4)}
             for i in order]
    return {"model_version": model_version, "top_k": top_k, "abstain": bool(top_k[0]["prob"] < threshold),
            "abstain_threshold": float(threshold), "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "used_location": bool(used_location)}


class StubClassifier:
    model_version = "stub"

    def classify(self, image_bytes, latlng=None):
        t0 = time.perf_counter()
        Image.open(io.BytesIO(image_bytes)).verify()  # reject non-images exactly like the real model
        seed = int.from_bytes(hashlib.sha256(image_bytes).digest()[:8], "big")
        logits = np.random.default_rng(seed).normal(0, 1.5, len(LABELS))
        probs = np.exp(logits) / np.exp(logits).sum()
        return _response(probs, 0.55, self.model_version, False, t0)


class ModelClassifier:
    def __init__(self, artifact_dir):
        from ml.infer import Predictor

        self.predictor = Predictor.from_artifact(artifact_dir)
        meta = self.predictor.meta
        if meta["classes"] != LABELS:
            raise ValueError("artifact class order != contracts/categories.json")
        self.model_version = meta["model_version"]
        self.geo = bool(meta.get("geo_prior_beta"))

    def classify(self, image_bytes, latlng=None):
        t0 = time.perf_counter()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        probs = self.predictor.probs([img], latlng=[latlng] if latlng else None)[0]
        _, threshold = self.predictor.calibration(with_location=latlng is not None)
        return _response(probs, threshold or UNCALIBRATED_THRESHOLD, self.model_version,
                         self.geo and latlng is not None, t0)


def make_classifier():
    if os.environ.get("CLASSIFIER", "stub") == "model":
        return ModelClassifier(os.environ.get("MODEL_ARTIFACT_DIR", str(ROOT / "artifacts" / "latest")))
    return StubClassifier()
