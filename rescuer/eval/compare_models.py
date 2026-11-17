"""Comparison of supervised classifiers for SOS triage (reviewer comments B5/B6).

Same corpus, same TF-IDF features (word unigrams+bigrams) and same stratified
5-fold protocol (seed 42) as the deployed pipeline. Reports classification
performance, hybrid performance with the rule tier, and computational cost:
training time, single-message prediction latency and serialized model size.
"""
import pickle, time, json, statistics, platform, sys
import numpy as np
import sklearn
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.naive_bayes import MultinomialNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import precision_recall_fscore_support, accuracy_score
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))  # rescuer/: training_data.py
from triage_eval_core import rule_classify, PRIORITY_ORDER, PRIORITY_RANK
from training_data import TRAINING_DATA

X = [t for t, _ in TRAINING_DATA]
y = np.array([l for _, l in TRAINING_DATA])
L = PRIORITY_ORDER
RULE = np.array([rule_classify(t) for t in X])

MODELS = {
    "Logistic regression (deployed)": lambda: LogisticRegression(max_iter=1000, class_weight="balanced"),
    "Linear SVM": lambda: LinearSVC(class_weight="balanced"),
    "Multinomial naive Bayes": lambda: MultinomialNB(),
    "k-nearest neighbours (k=5, cosine)": lambda: KNeighborsClassifier(n_neighbors=5, metric="cosine"),
    "Decision tree": lambda: DecisionTreeClassifier(class_weight="balanced", random_state=42),
    "Random forest (200 trees)": lambda: RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42),
}


def pipe(make):
    return Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
                     ("clf", make())])


def hybrid(a, b):
    return a if PRIORITY_RANK[a] <= PRIORITY_RANK[b] else b


def scores(pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, labels=L, zero_division=0)
    _, _, mf, _ = precision_recall_fscore_support(y, pred, labels=L, average="macro", zero_division=0)
    under = sum(PRIORITY_RANK[a] > PRIORITY_RANK[t] for t, a in zip(y, pred))
    over = sum(PRIORITY_RANK[a] < PRIORITY_RANK[t] for t, a in zip(y, pred))
    return dict(acc=accuracy_score(y, pred), macro_f1=mf, crit_p=p[0], crit_r=r[0], crit_f1=f[0],
                under=int(under), over=int(over))


out = {"env": {"python": platform.python_version(), "sklearn": sklearn.__version__,
               "cpu": platform.processor() or platform.machine(), "machine": platform.machine()}}
for name, make in MODELS.items():
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    ml = cross_val_predict(pipe(make), X, y, cv=skf)
    hyb = np.array([hybrid(a, b) for a, b in zip(RULE, ml)])
    res = {"alone": scores(ml), "hybrid": scores(hyb)}
    # stability over 20 fold assignments
    mf, cr, hcr = [], [], []
    for seed in range(20):
        sk = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
        m = cross_val_predict(pipe(make), X, y, cv=sk)
        s = scores(m); h = scores(np.array([hybrid(a, b) for a, b in zip(RULE, m)]))
        mf.append(s["macro_f1"]); cr.append(s["crit_r"]); hcr.append(h["crit_r"])
    res["seeds20"] = {k: (float(np.mean(v)), float(np.std(v, ddof=1))) for k, v in
                      (("macro_f1", mf), ("crit_r", cr), ("hyb_crit_r", hcr))}
    # computational cost on the full corpus
    tt = []
    for _ in range(7):
        m = pipe(make); t0 = time.perf_counter(); m.fit(X, y); tt.append(time.perf_counter() - t0)
    lat = []
    for _ in range(3):
        for t in X:
            t0 = time.perf_counter(); m.predict([t]); lat.append(time.perf_counter() - t0)
    res["train_ms"] = statistics.median(tt) * 1000
    res["predict_ms_median"] = statistics.median(lat) * 1000
    res["predict_ms_p95"] = float(np.percentile(lat, 95)) * 1000
    res["model_kb"] = len(pickle.dumps(m)) / 1024
    res["vocab"] = len(m.named_steps["tfidf"].vocabulary_)
    out[name] = res
    a, h, s = res["alone"], res["hybrid"], res["seeds20"]
    print(f"{name:38s} acc {a['acc']:.3f} mF1 {a['macro_f1']:.3f} critR {a['crit_r']:.3f} critP {a['crit_p']:.3f} "
          f"| hyb critR {h['crit_r']:.3f} over {h['over']} under {h['under']} "
          f"| 20seeds mF1 {s['macro_f1'][0]:.3f}±{s['macro_f1'][1]:.3f} critR {s['crit_r'][0]:.3f}±{s['crit_r'][1]:.3f} "
          f"| train {res['train_ms']:.1f} ms pred {res['predict_ms_median']:.3f} ms p95 {res['predict_ms_p95']:.3f} "
          f"size {res['model_kb']:.0f} kB vocab {res['vocab']}")

# rule tier latency for reference
lat = []
for _ in range(3):
    for t in X:
        t0 = time.perf_counter(); rule_classify(t); lat.append(time.perf_counter() - t0)
out["rule_predict_ms_median"] = statistics.median(lat) * 1000
print("rule tier pred ms", out["rule_predict_ms_median"])
json.dump(out, open("compare_models.json", "w"), indent=1, default=float)
