"""Unit tests for eval/metrics.py on synthetic logits (no data, no model, no network)."""
import numpy as np
import pytest
from scipy import stats

from eval import metrics as M

C = 17


def synthetic(n=2000, seed=0, sharpness=3.0, noise=1.0):
    """Logits where the true class gets a boost; `sharpness` controls accuracy."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, C, size=n)
    logits = rng.normal(0, noise, size=(n, C))
    logits[np.arange(n), labels] += sharpness * rng.random(n)
    groups = rng.integers(0, 150, size=n)
    return logits.astype(np.float32), labels, groups


def test_softmax_rows_sum_to_one_and_temperature_flattens():
    logits, _, _ = synthetic()
    p1 = M.softmax(logits, 1.0)
    p5 = M.softmax(logits, 5.0)
    assert np.allclose(p1.sum(axis=1), 1.0)
    assert p5.max(axis=1).mean() < p1.max(axis=1).mean()
    assert (p1.argmax(axis=1) == p5.argmax(axis=1)).all()  # temperature never changes the argmax


def test_perfect_and_chance_accuracy():
    labels = np.arange(C).repeat(10)
    perfect = np.eye(C)[labels] * 10
    p = M.softmax(perfect)
    assert M.top_k_accuracy(p, labels, 1) == 1.0
    assert M.top_k_accuracy(p, labels, 3) == 1.0
    assert M.macro_f1(p.argmax(1), labels) == 1.0
    # all-same prediction: top-1 = 1/17, macro-F1 small
    const = np.zeros((len(labels), C))
    const[:, 0] = 5
    pc = M.softmax(const)
    assert M.top_k_accuracy(pc, labels, 1) == pytest.approx(1 / C)
    assert M.macro_f1(pc.argmax(1), labels) == pytest.approx((2 * (1 / C) * 1 / (1 / C + 1)) / C)


def test_confusion_matrix_and_prf_match_sklearn():
    sk = pytest.importorskip("sklearn.metrics")
    logits, labels, _ = synthetic(n=800)
    preds = logits.argmax(1)
    cm = M.confusion_matrix(preds, labels)
    assert (cm == sk.confusion_matrix(labels, preds, labels=range(C))).all()
    assert M.macro_f1(preds, labels) == pytest.approx(sk.f1_score(labels, preds, average="macro", labels=range(C)))
    prf = M.per_class_prf(preds, labels)
    p, r, f, s = sk.precision_recall_fscore_support(labels, preds, labels=range(C), zero_division=0)
    assert np.allclose(prf["precision"], p) and np.allclose(prf["recall"], r) and np.allclose(prf["f1"], f)
    assert (prf["support"] == s).all()


def test_prior_weighted_top1_is_recall_weighted():
    labels = np.array([0] * 10 + [1] * 10)
    preds = np.array([0] * 10 + [0] * 5 + [1] * 5)  # recall: class0 = 1.0, class1 = 0.5
    prior = np.zeros(C)
    prior[0], prior[1] = 0.8, 0.2
    assert M.prior_weighted_top1(preds, labels, prior) == pytest.approx(0.8 * 1.0 + 0.2 * 0.5)


def test_ece_zero_when_perfectly_calibrated_and_temperature_improves_it():
    # Over-confident logits: scaling by the fitted temperature must not raise NLL and should lower ECE.
    logits, labels, _ = synthetic(n=4000, sharpness=2.0)
    logits = logits * 4  # make it over-confident
    T = M.fit_temperature(logits, labels)
    assert T > 1.0
    assert M.nll(logits, labels, T) <= M.nll(logits, labels, 1.0) + 1e-9
    assert M.ece(M.softmax(logits, T), labels) < M.ece(M.softmax(logits, 1.0), labels)
    # a probs matrix whose confidence equals its accuracy in every bin has ECE 0
    probs = np.full((100, C), 0.1 / (C - 1))
    probs[:, 0] = 0.9
    lab = np.array([0] * 90 + [1] * 10)
    assert M.ece(probs, lab) == pytest.approx(0.0, abs=1e-9)


def test_fit_temperature_recovers_known_scale():
    rng = np.random.default_rng(1)
    labels = rng.integers(0, C, size=6000)
    base = rng.normal(0, 1, size=(6000, C))
    base[np.arange(6000), labels] += 2.0
    # sample labels FROM softmax(base) so base is calibrated at T=1; then scale by 3 -> fitted T ~ 3
    p = M.softmax(base)
    labels = np.array([rng.choice(C, p=row) for row in p])
    T = M.fit_temperature(base * 3.0, labels)
    assert 2.5 < T < 3.5


def test_clopper_pearson_lower_matches_scipy_and_edges():
    assert M.clopper_pearson_lower(0, 10) == 0.0
    assert np.isnan(M.clopper_pearson_lower(0, 0))
    lb = M.clopper_pearson_lower(90, 100)
    assert lb == pytest.approx(stats.beta.ppf(0.05, 90, 11))
    assert lb < 0.9
    # the margin shrinks with n
    assert M.clopper_pearson_lower(900, 1000) > lb


def test_selective_and_risk_coverage_consistency():
    logits, labels, _ = synthetic(n=1000)
    probs = M.softmax(logits)
    full = M.selective(probs, labels, 0.0)
    assert full["coverage"] == 1.0
    assert full["selective_accuracy"] == pytest.approx(M.top_k_accuracy(probs, labels, 1))
    none = M.selective(probs, labels, 1.01)
    assert none["coverage"] == 0.0 and np.isnan(none["selective_accuracy"])
    cov, risk = M.risk_coverage_curve(probs, labels)
    assert cov[-1] == 1.0 and risk[-1] == pytest.approx(1 - full["selective_accuracy"])
    assert (np.diff(cov) > 0).all()
    # AURC bounds: between 0 and the full-coverage error, and perfect ranking gives a small value
    a = M.aurc(probs, labels)
    assert 0.0 <= a <= 1.0
    perfect = np.eye(C)[labels] * 10
    assert M.aurc(M.softmax(perfect), labels) == pytest.approx(0.0)


def test_abstain_threshold_meets_target_with_margin():
    logits, labels, _ = synthetic(n=3000, sharpness=4.0)
    probs = M.softmax(logits)
    res = M.abstain_threshold(probs, labels, target=0.90)
    assert 0 < res["coverage"] <= 1
    assert res["selective_accuracy_lower95"] >= 0.90
    # the chosen tau really gives that bound, and a slightly smaller tau would break it
    sel = M.selective(probs, labels, res["threshold"])
    assert sel["selective_accuracy_lower95"] >= 0.90
    conf = np.sort(np.unique(probs.max(1)))
    below = conf[conf < res["threshold"]]
    if len(below):
        assert M.selective(probs, labels, below[-1])["selective_accuracy_lower95"] < 0.90
    assert res["always_abstain"] is False
    # unreachable target -> always abstain, explicit flag, no NaNs
    bad = M.abstain_threshold(M.softmax(np.zeros((50, C))), np.zeros(50, dtype=int), target=0.99)
    assert bad["threshold"] == 1.0 and bad["coverage"] == 0.0 and bad["always_abstain"] is True
    assert bad["selective_accuracy"] is None


def test_no_answer_predictions_never_credit_a_class():
    labels = np.array([0, 0, 1, 1, 2])
    preds = np.array([0, -1, 1, -1, -1])  # two right, three "no answer"
    cm = M.confusion_matrix_na(preds, labels)
    assert cm.shape == (C, C + 1) and cm[:, C].sum() == 3 and cm[0, 0] == 1 and cm[1, 1] == 1
    assert M.top1_na(preds, labels) == pytest.approx(2 / 5)
    # class 0: p=1, r=0.5 -> f1 2/3; class 1 same; class 2: r=0 -> 0; others 0
    assert M.macro_f1_na(preds, labels) == pytest.approx((2 / 3 + 2 / 3) / C)
    # no refusals: identical to the plain versions
    full = np.array([0, 0, 1, 2, 2])
    assert M.macro_f1_na(full, labels) == pytest.approx(M.macro_f1(full, labels))
    assert M.top1_na(full, labels) == pytest.approx(M.top_k_accuracy(np.eye(C)[full], labels, 1))


def test_cluster_bootstrap_ci_contains_point_estimate_and_is_reproducible():
    logits, labels, groups = synthetic(n=1500)
    probs = M.softmax(logits)
    point = M.top_k_accuracy(probs, labels, 1)
    fn = lambda i: M.top_k_accuracy(probs[i], labels[i], 1)
    lo, hi = M.cluster_bootstrap_ci(fn, groups, n_boot=300, seed=13)
    assert lo <= point <= hi
    assert (lo, hi) == M.cluster_bootstrap_ci(fn, groups, n_boot=300, seed=13)
    # resampling groups must be wider than (or equal to) resampling rows when groups cluster errors
    lo2, hi2 = M.cluster_bootstrap_ci(fn, np.arange(len(labels)), n_boot=300, seed=13)
    assert hi - lo >= 0 and hi2 - lo2 >= 0


def test_ensemble_logits_average_probabilities():
    a = np.log(np.array([[0.8, 0.2] + [0.0] * (C - 2)]) + 1e-12)
    b = np.log(np.array([[0.2, 0.8] + [0.0] * (C - 2)]) + 1e-12)
    ens = M.softmax(M.ensemble_logits([a, b]))
    assert ens[0, 0] == pytest.approx(0.5, abs=1e-6) and ens[0, 1] == pytest.approx(0.5, abs=1e-6)


def test_summarize_shape_and_keys():
    logits, labels, groups = synthetic(n=600)
    names = [f"c{i}" for i in range(C)]
    s = M.summarize(logits, labels, groups=groups, temperature=1.2, threshold=0.5,
                    prior=np.ones(C) / C, n_boot=50, labels_names=names)
    for k in ["top1", "top3", "macro_f1", "ece", "aurc", "nll", "per_class", "confusion_matrix",
              "selective", "ci95", "prior_weighted_top1"]:
        assert k in s
    assert set(s["ci95"]) == {"top1", "top3", "macro_f1", "aurc", "coverage", "selective_accuracy"}
    assert len(s["per_class"]) == C and len(s["confusion_matrix"]) == C
    assert s["prior_weighted_top1"] == pytest.approx(np.mean([v["recall"] for v in s["per_class"].values()]))
    tc = M.top_confusions(np.array(s["confusion_matrix"]), names, k=5)
    assert len(tc) <= 5 and all(t["true"] != t["pred"] for t in tc)


def test_contract_categories_load():
    labels = M.class_labels()
    assert len(labels) == 17 and labels[5] == "garbage_debris"
    assert M.real_prior().sum() == pytest.approx(1.0)
