"""Triage evaluation: rule / learned / hybrid, cross-validated on the 200-message synthetic corpus."""
import json, sys
import numpy as np
from collections import Counter
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (precision_recall_fscore_support, confusion_matrix, accuracy_score)
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))  # rescuer/: training_data.py
from triage_eval_core import rule_classify, make_pipeline, PRIORITY_ORDER, PRIORITY_RANK
from training_data import TRAINING_DATA

X = [t for t, _ in TRAINING_DATA]
y = np.array([l for _, l in TRAINING_DATA])
L = PRIORITY_ORDER


def hybrid(a, b):
    """Escalate on the more urgent of the two."""
    return a if PRIORITY_RANK[a] <= PRIORITY_RANK[b] else b


def report(name, y_true, y_pred):
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=L, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=L)
    # false escalation: predicted more urgent than truth
    esc = sum(PRIORITY_RANK[pr] < PRIORITY_RANK[t] for t, pr in zip(y_true, y_pred))
    under = sum(PRIORITY_RANK[pr] > PRIORITY_RANK[t] for t, pr in zip(y_true, y_pred))
    # non-critical messages wrongly flagged CRITICAL
    noncrit = [i for i, t in enumerate(y_true) if t != "CRITICAL"]
    fp_crit = sum(y_pred[i] == "CRITICAL" for i in noncrit)
    mp, mr, mf, _ = precision_recall_fscore_support(y_true, y_pred, labels=L, average="macro", zero_division=0)
    return {
        "name": name,
        "accuracy": accuracy_score(y_true, y_pred),
        "per_class": {c: {"precision": p[i], "recall": r[i], "f1": f[i], "support": int(s[i])} for i, c in enumerate(L)},
        "macro": {"precision": mp, "recall": mr, "f1": mf},
        "confusion": cm.tolist(),
        "over_triage_rate": esc / len(y_true),
        "under_triage_rate": under / len(y_true),
        "critical_false_alarm_rate": fp_crit / len(noncrit),
        "critical_false_alarms": fp_crit,
    }


def run(seed, folds=5):
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    ml = cross_val_predict(make_pipeline(), X, y, cv=skf)
    rule = np.array([rule_classify(t) for t in X])
    hyb = np.array([hybrid(a, b) for a, b in zip(rule, ml)])
    return rule, ml, hyb


if __name__ == "__main__":
    out = {}
    rule, ml, hyb = run(42)
    for name, pred in (("rule", rule), ("learned", ml), ("hybrid", hyb)):
        out[name] = report(name, y, pred)
    # stability across seeds (learned + hybrid depend on fold split)
    stab = {"learned": [], "hybrid": []}
    for seed in range(20):
        r_, m_, h_ = run(seed)
        for n, pr in (("learned", m_), ("hybrid", h_)):
            _, rc, _, _ = precision_recall_fscore_support(y, pr, labels=["CRITICAL"], zero_division=0)
            stab[n].append(float(rc[0]))
    out["critical_recall_over_20_seeds"] = {k: {"mean": float(np.mean(v)), "sd": float(np.std(v, ddof=1)),
                                                 "min": float(min(v)), "max": float(max(v))} for k, v in stab.items()}
    json.dump(out, open("results.json", "w"), indent=2, default=float)

    for n in ("rule", "learned", "hybrid"):
        o = out[n]
        print(f"\n=== {n.upper()}  accuracy={o['accuracy']:.3f}  macro-F1={o['macro']['f1']:.3f}")
        print(f"{'class':9s} {'prec':>6s} {'rec':>6s} {'F1':>6s} {'n':>4s}")
        for c in L:
            d = o["per_class"][c]
            print(f"{c:9s} {d['precision']:6.3f} {d['recall']:6.3f} {d['f1']:6.3f} {d['support']:4d}")
        print("confusion (rows=true, cols=pred, order C/H/M/L):")
        for c, row in zip(L, o["confusion"]):
            print(f"  {c:9s} {row}")
        print(f"over-triage {o['over_triage_rate']:.3f} | under-triage {o['under_triage_rate']:.3f} | "
              f"non-critical flagged CRITICAL {o['critical_false_alarms']} ({o['critical_false_alarm_rate']:.3f})")
    print("\nCRITICAL recall over 20 CV seeds:", json.dumps(out["critical_recall_over_20_seeds"], indent=1))
