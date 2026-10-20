#!/usr/bin/env python3
"""
RescueNet - Triage evaluation harness
======================================
Regenerates the triage results of the paper (Table 5 and the supporting
statistics in Section 3.3): the three configurations (literal rule tier, the
TF-IDF + logistic-regression model, and their hybrid), evaluated out of
sample on the balanced 200-message corpus (50 per class) in training_data.py.

The learned model, alone and inside the hybrid, is scored by five-fold
stratified cross-validation (seed 42), rebuilt from the training fold at each
split, so no message contributes to the model that classifies it. The rule
tier has no fitted component and is applied directly.

Outputs:
  - Table 5: accuracy, macro-F1, per-class recall, critical recall with a
    stratified-bootstrap 95% CI (2000 resamples), over-triage and
    under-triage counts.
  - McNemar exact tests (hybrid vs model) on critical recall and on
    over-triage.
  - Stability of the hybrid critical recall over ten random fold assignments.
  - Character n-gram control (3-5 and 2-5 grams) under the same protocol.

Reproducible: fixed seeds throughout. No network, no external data.

Usage:  python3 eval_triage.py
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import f1_score
from scipy.stats import binomtest

from training_data import TRAINING_DATA
from priority_classifier import _rule_based_classify, PRIORITY_ORDER

RANK = {p: i for i, p in enumerate(PRIORITY_ORDER)}   # 0 = most urgent
X = np.array([t for t, _ in TRAINING_DATA], dtype=object)
y = np.array([l for _, l in TRAINING_DATA], dtype=object)


def word_pipe():
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


def char_pipe(lo, hi):
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(lo, hi),
                                  min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


def cv_predict(pipe_factory, seed=42):
    """Out-of-sample predictions via 5-fold stratified CV."""
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    pred = np.empty(len(y), dtype=object)
    for tr, te in skf.split(X, y):
        pred[te] = pipe_factory().fit(X[tr], y[tr]).predict(X[te])
    return pred


def rule_predict():
    return np.array([_rule_based_classify(t)["priority"] for t in X], dtype=object)


def hybrid(rule_pred, ml_pred):
    return np.array([min(r, m, key=lambda z: RANK[z])
                     for r, m in zip(rule_pred, ml_pred)], dtype=object)


def accuracy(pred):
    return float((pred == y).mean())


def macro_f1(pred):
    return float(f1_score(y, pred, average="macro", labels=PRIORITY_ORDER))


def critical_recall(pred):
    idx = (y == "CRITICAL")
    return float((pred[idx] == "CRITICAL").mean())


def over_triage(pred):
    """Predicted strictly more urgent than the true label."""
    return int(sum(RANK[p] < RANK[t] for p, t in zip(pred, y)))


def under_triage(pred):
    """Predicted strictly less urgent than the true label."""
    return int(sum(RANK[p] > RANK[t] for p, t in zip(pred, y)))


def bootstrap_ci(pred, metric=critical_recall, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    classes = PRIORITY_ORDER
    idx_by_class = {c: np.where(y == c)[0] for c in classes}
    vals = []
    for _ in range(n):
        res = np.concatenate([rng.choice(idx_by_class[c], size=len(idx_by_class[c]),
                                          replace=True) for c in classes])
        yb, pb = y[res], pred[res]
        ib = (yb == "CRITICAL")
        vals.append((pb[ib] == "CRITICAL").mean())
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def mcnemar_exact(a_correct, b_correct):
    """Exact two-sided McNemar on paired boolean correctness vectors."""
    b = int(np.sum(a_correct & ~b_correct))   # a right, b wrong
    c = int(np.sum(~a_correct & b_correct))   # b right, a wrong
    n = b + c
    if n == 0:
        return b, c, 1.0
    p = binomtest(min(b, c), n, 0.5, alternative="two-sided").pvalue
    return b, c, float(p)


def main():
    rule_pred = rule_predict()
    ml_pred = cv_predict(word_pipe)
    hyb_pred = hybrid(rule_pred, ml_pred)

    print("=" * 78)
    print("Table 5 - Triage performance on the 200-message corpus (50 per class)")
    print("=" * 78)
    hdr = f"{'config':8s} {'acc':>6s} {'mF1':>6s} {'critRec':>8s} " \
          f"{'crit 95% CI':>14s} {'over':>5s} {'under':>6s}"
    print(hdr)
    for name, pr in [("rule", rule_pred), ("ml", ml_pred), ("hybrid", hyb_pred)]:
        lo, hi = bootstrap_ci(pr)
        print(f"{name:8s} {accuracy(pr):6.3f} {macro_f1(pr):6.3f} "
              f"{critical_recall(pr):8.3f} [{lo:.2f}, {hi:.2f}]"
              f"   {over_triage(pr):5d} {under_triage(pr):6d}")

    print("\nPer-class recall")
    for name, pr in [("rule", rule_pred), ("ml", ml_pred), ("hybrid", hyb_pred)]:
        rec = {c: (pr[y == c] == c).mean() for c in PRIORITY_ORDER}
        print(f"  {name:8s} " + "  ".join(f"{c}={rec[c]:.3f}" for c in PRIORITY_ORDER))

    print("\nMcNemar exact tests (hybrid vs model)")
    ci = (y == "CRITICAL")
    b, c, p = mcnemar_exact(hyb_pred[ci] == "CRITICAL", ml_pred[ci] == "CRITICAL")
    print(f"  critical recall : hybrid-only={b}  model-only={c}  p={p:.3f}")
    over_h = np.array([RANK[pp] < RANK[t] for pp, t in zip(hyb_pred, y)])
    over_m = np.array([RANK[pp] < RANK[t] for pp, t in zip(ml_pred, y)])
    # discordant on "correctly NOT over-triaged": model right (no over), hybrid wrong (over)
    b2 = int(np.sum(over_h & ~over_m)); c2 = int(np.sum(~over_h & over_m))
    n2 = b2 + c2
    p2 = binomtest(min(b2, c2), n2, 0.5).pvalue if n2 else 1.0
    print(f"  over-triage     : hybrid-only={b2}  model-only={c2}  p={p2:.2e}")

    print("\nStability of hybrid critical recall over 10 random fold assignments")
    vals = []
    for s in range(10):
        mlp = cv_predict(word_pipe, seed=s)
        vals.append(critical_recall(hybrid(rule_pred, mlp)))
    vals = np.array(vals)
    print(f"  mean={vals.mean():.3f}  sd={vals.std(ddof=1):.3f}  "
          f"range=[{vals.min():.2f}, {vals.max():.2f}]")

    print("\nCharacter n-gram control (same protocol as the word model)")
    for lo, hi in [(3, 5), (2, 5)]:
        cp = cv_predict(lambda: char_pipe(lo, hi))
        print(f"  char {lo}-{hi}-gram : acc={accuracy(cp):.3f} "
              f"critRec={critical_recall(cp):.3f}")
    wp = ml_pred
    print(f"  word 1-2-gram : acc={accuracy(wp):.3f} critRec={critical_recall(wp):.3f}")


if __name__ == "__main__":
    main()
