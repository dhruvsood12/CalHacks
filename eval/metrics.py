"""Evaluation metrics for the 17-way SF311 photo classifier (role B).

Everything here takes raw logits (N, C) and integer labels (N,). Nothing reads a
split CSV; callers (val_report.py, calibrate.py, final_eval.py) load the data and
pass arrays in. Built and unit-tested on synthetic logits so it is correct before
A's first val_logits.npz lands.

Metrics (PLAN 3.5-3.6):
  top-1, top-3, macro-F1, per-class precision/recall/F1, confusion matrix,
  ECE (15 bins) before/after temperature scaling,
  selective accuracy + coverage at a threshold, the risk-coverage curve, AURC,
  Clopper-Pearson lower bound on selective accuracy,
  cluster bootstrap 95% CI over `group` ids,
  prior-weighted top-1 (sum of real_prior[c] * recall[c]).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from scipy import stats
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parent.parent
N_CLASSES = 17


# ----------------------------------------------------------------------------
# Class list / prior from the frozen contract
# ----------------------------------------------------------------------------
def load_categories(path: Path | None = None) -> list[dict]:
    path = path or ROOT / "contracts" / "categories.json"
    cats = json.loads(Path(path).read_text(encoding="utf-8"))["classes"]
    assert [c["index"] for c in cats] == list(range(len(cats))), "categories.json index order broken"
    return cats


def class_labels(path: Path | None = None) -> list[str]:
    return [c["label"] for c in load_categories(path)]


def real_prior(path: Path | None = None) -> np.ndarray:
    p = np.array([c["real_prior"] for c in load_categories(path)], dtype=np.float64)
    return p / p.sum()


# ----------------------------------------------------------------------------
# Probabilities
# ----------------------------------------------------------------------------
def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Row-wise softmax of logits / temperature, numerically stable."""
    z = np.asarray(logits, dtype=np.float64) / float(temperature)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def ensemble_logits(member_logits: Sequence[np.ndarray]) -> np.ndarray:
    """Ensemble per contracts/predictor.md: average member softmax probabilities,
    return the log of the average (temperature is applied to that by the caller)."""
    probs = np.mean([softmax(m) for m in member_logits], axis=0)
    return np.log(np.clip(probs, 1e-12, 1.0))


def nll(logits: np.ndarray, labels: np.ndarray, temperature: float = 1.0) -> float:
    p = softmax(logits, temperature)
    return float(-np.mean(np.log(np.clip(p[np.arange(len(labels)), labels], 1e-12, 1.0))))


def fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    """One scalar temperature minimising val NLL (Guo et al. 2017). Searched in log space."""
    labels = np.asarray(labels)
    res = minimize_scalar(lambda t: nll(logits, labels, np.exp(t)),
                          bounds=(np.log(0.05), np.log(20.0)), method="bounded")
    return float(np.exp(res.x))


# ----------------------------------------------------------------------------
# Accuracy-style metrics
# ----------------------------------------------------------------------------
def top_k_accuracy(probs: np.ndarray, labels: np.ndarray, k: int = 1) -> float:
    labels = np.asarray(labels)
    topk = np.argsort(-probs, axis=1, kind="stable")[:, :k]
    return float((topk == labels[:, None]).any(axis=1).mean())


def confusion_matrix(preds: np.ndarray, labels: np.ndarray, n_classes: int = N_CLASSES) -> np.ndarray:
    """cm[true, pred] counts."""
    preds, labels = np.asarray(preds), np.asarray(labels)
    return np.bincount(labels * n_classes + preds, minlength=n_classes * n_classes).reshape(n_classes, n_classes)


def per_class_prf(preds: np.ndarray, labels: np.ndarray, n_classes: int = N_CLASSES) -> dict[str, np.ndarray]:
    cm = confusion_matrix(preds, labels, n_classes).astype(np.float64)
    tp = np.diag(cm)
    pred_n = cm.sum(axis=0)
    true_n = cm.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.where(pred_n > 0, tp / pred_n, 0.0)
        recall = np.where(true_n > 0, tp / true_n, 0.0)
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), 0.0)
    return {"precision": precision, "recall": recall, "f1": f1, "support": true_n.astype(int)}


def macro_f1(preds: np.ndarray, labels: np.ndarray, n_classes: int = N_CLASSES) -> float:
    return float(per_class_prf(preds, labels, n_classes)["f1"].mean())


def prior_weighted_top1(preds: np.ndarray, labels: np.ndarray, prior: np.ndarray,
                        n_classes: int = N_CLASSES) -> float:
    """Accuracy the model would have on the real (skewed) class mix: sum_c prior[c] * recall[c]."""
    recall = per_class_prf(preds, labels, n_classes)["recall"]
    prior = np.asarray(prior, dtype=np.float64)
    return float(np.sum(prior / prior.sum() * recall))


# ----------------------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------------------
def ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 15) -> float:
    """Expected calibration error on the max-probability, equal-width bins."""
    labels = np.asarray(labels)
    conf = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == labels).astype(np.float64)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1], right=True), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


# ----------------------------------------------------------------------------
# Selective prediction / abstention
# ----------------------------------------------------------------------------
def selective(probs: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    """Coverage and accuracy when the model only answers if max-prob >= threshold."""
    labels = np.asarray(labels)
    conf = probs.max(axis=1)
    covered = conf >= threshold
    n = int(covered.sum())
    k = int((probs.argmax(axis=1)[covered] == labels[covered]).sum())
    return {
        "threshold": float(threshold),
        "coverage": n / len(labels) if len(labels) else 0.0,
        "n_covered": n,
        "n_correct": k,
        "selective_accuracy": k / n if n else float("nan"),
        "selective_accuracy_lower95": clopper_pearson_lower(k, n) if n else float("nan"),
    }


def risk_coverage_curve(probs: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sort by confidence descending; coverage[i] = (i+1)/N, risk[i] = error rate among the first i+1."""
    labels = np.asarray(labels)
    conf = probs.max(axis=1)
    order = np.argsort(-conf, kind="stable")
    wrong = (probs.argmax(axis=1)[order] != labels[order]).astype(np.float64)
    n = np.arange(1, len(labels) + 1)
    return n / len(labels), np.cumsum(wrong) / n


def aurc(probs: np.ndarray, labels: np.ndarray) -> float:
    """Area under the risk-coverage curve (lower is better), trapezoid rule from coverage 0 to 1."""
    cov, risk = risk_coverage_curve(probs, labels)
    cov = np.concatenate([[0.0], cov])
    risk = np.concatenate([[risk[0]], risk])
    trap = getattr(np, "trapezoid", None) or np.trapz
    return float(trap(risk, cov))


def clopper_pearson_lower(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided lower (1-alpha) Clopper-Pearson bound on a binomial proportion k/n."""
    if n == 0:
        return float("nan")
    if k == 0:
        return 0.0
    return float(stats.beta.ppf(alpha, k, n - k + 1))


def abstain_threshold(probs: np.ndarray, labels: np.ndarray, target: float = 0.90, alpha: float = 0.05) -> dict:
    """Smallest max-probability threshold whose Clopper-Pearson lower (1-alpha) bound on
    selective accuracy is >= target (PLAN 3.5). The margin is what keeps the held-out
    selective accuracy at >= target with (1-alpha) confidence instead of ~50%.

    Returns the threshold, its coverage and bound; threshold 1.0 and coverage 0 if no
    threshold reaches the target (the caller should treat that as "always abstain")."""
    labels = np.asarray(labels)
    conf = probs.max(axis=1)
    correct = probs.argmax(axis=1) == labels
    order = np.argsort(-conf, kind="stable")
    conf_s, correct_s = conf[order], correct[order]
    cum_k = np.cumsum(correct_s)
    cum_n = np.arange(1, len(labels) + 1)
    # Only evaluate at the LAST index of each tie group so "conf >= tau" is exact.
    last_of_tie = np.ones(len(conf_s), dtype=bool)
    last_of_tie[:-1] = conf_s[:-1] != conf_s[1:]
    idx = np.nonzero(last_of_tie)[0]
    lower = np.array([clopper_pearson_lower(int(cum_k[i]), int(cum_n[i]), alpha) for i in idx])
    ok = np.nonzero(lower >= target)[0]
    if len(ok) == 0:
        return {"threshold": 1.0, "coverage": 0.0, "selective_accuracy": float("nan"),
                "selective_accuracy_lower95": float("nan"), "target": target, "alpha": alpha}
    i = idx[ok[-1]]  # largest prefix (= smallest threshold) that still meets the bound
    return {"threshold": float(conf_s[i]), "coverage": float(cum_n[i] / len(labels)),
            "selective_accuracy": float(cum_k[i] / cum_n[i]),
            "selective_accuracy_lower95": float(lower[ok[-1]]), "target": target, "alpha": alpha}


# ----------------------------------------------------------------------------
# Uncertainty: cluster bootstrap over map-block groups
# ----------------------------------------------------------------------------
def cluster_bootstrap_ci(metric_fn: Callable[[np.ndarray], float], groups: Sequence, n_boot: int = 1000,
                         seed: int = 13, alpha: float = 0.05) -> tuple[float, float]:
    """95% percentile CI of metric_fn(index_array) by resampling GROUP ids with replacement.
    Rows in the same group (geohash-7 block) always move together, which is what makes the
    interval honest for spatially clustered photos (PLAN 3.6)."""
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    members = [np.nonzero(inv == g)[0] for g in range(len(uniq))]
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(uniq), size=len(uniq))
        idx = np.concatenate([members[g] for g in pick])
        vals[b] = metric_fn(idx)
    if not np.isfinite(vals).any():  # e.g. selective accuracy at zero coverage
        return float("nan"), float("nan")
    return (float(np.nanpercentile(vals, 100 * alpha / 2)),
            float(np.nanpercentile(vals, 100 * (1 - alpha / 2))))


# ----------------------------------------------------------------------------
# One call that produces the dict every report is built from
# ----------------------------------------------------------------------------
def summarize(logits: np.ndarray, labels: np.ndarray, groups: Sequence | None = None, temperature: float = 1.0,
              threshold: float | None = None, prior: np.ndarray | None = None, n_boot: int = 1000,
              seed: int = 13, labels_names: list[str] | None = None) -> dict:
    """Full metric bundle on one split. `temperature` scales the logits first; `threshold`
    (if given) adds selective metrics at that abstain threshold. With `groups`, every headline
    number gets a cluster-bootstrap 95% CI."""
    logits = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(labels)
    n_classes = logits.shape[1]
    names = labels_names or class_labels()
    probs = softmax(logits, temperature)
    preds = probs.argmax(axis=1)
    prf = per_class_prf(preds, labels, n_classes)
    out = {
        "n": int(len(labels)),
        "temperature": float(temperature),
        "top1": top_k_accuracy(probs, labels, 1),
        "top3": top_k_accuracy(probs, labels, 3),
        "macro_f1": macro_f1(preds, labels, n_classes),
        "nll": nll(logits, labels, temperature),
        "ece": ece(probs, labels),
        "ece_uncalibrated": ece(softmax(logits, 1.0), labels),
        "aurc": aurc(probs, labels),
        "per_class": {names[c]: {"precision": float(prf["precision"][c]), "recall": float(prf["recall"][c]),
                                 "f1": float(prf["f1"][c]), "support": int(prf["support"][c])}
                      for c in range(n_classes)},
        "confusion_matrix": confusion_matrix(preds, labels, n_classes).tolist(),
    }
    if prior is not None:
        out["prior_weighted_top1"] = prior_weighted_top1(preds, labels, prior, n_classes)
    if threshold is not None:
        out["selective"] = selective(probs, labels, threshold)
    if groups is not None:
        groups = np.asarray(groups)
        fns = {
            "top1": lambda i: top_k_accuracy(probs[i], labels[i], 1),
            "top3": lambda i: top_k_accuracy(probs[i], labels[i], 3),
            "macro_f1": lambda i: macro_f1(preds[i], labels[i], n_classes),
            "aurc": lambda i: aurc(probs[i], labels[i]),
        }
        if threshold is not None:
            fns["coverage"] = lambda i: selective(probs[i], labels[i], threshold)["coverage"]
            fns["selective_accuracy"] = lambda i: selective(probs[i], labels[i], threshold)["selective_accuracy"]
        out["ci95"] = {k: list(cluster_bootstrap_ci(f, groups, n_boot=n_boot, seed=seed)) for k, f in fns.items()}
        out["n_groups"] = int(len(np.unique(groups)))
        out["n_boot"] = int(n_boot)
    return out


def top_confusions(cm: np.ndarray, names: list[str], k: int = 5) -> list[dict]:
    """The k most frequent off-diagonal (true, pred) pairs. Feeds the error analysis / model card."""
    cm = np.asarray(cm)
    off = cm.copy()
    np.fill_diagonal(off, 0)
    flat = np.argsort(-off, axis=None, kind="stable")[:k]
    out = []
    for f in flat:
        t, p = divmod(int(f), cm.shape[1])
        if off[t, p] == 0:
            break
        out.append({"true": names[t], "pred": names[p], "count": int(off[t, p]),
                    "share_of_true": float(off[t, p] / max(cm[t].sum(), 1))})
    return out
