#!/usr/bin/env python3
"""
RescueNet - SOS Message Priority Classifier
=============================================
Classifies the urgency of an SOS message from its free-text content, so the
rescuer can triage multiple simultaneous alerts (which one to reach first).

Two backends:
  1) ML backend  (TF-IDF + Logistic Regression) - used if scikit-learn is
     installed and a trained model is available. Trained on training_data.py.
  2) Rule backend (keyword matching) - always available as fallback, so the
     rescuer NEVER loses priority information even without sklearn installed.

The rule backend is not a "worse copy" of the ML one: it is a transparent,
auditable safety net. If the ML model fails to load for any reason, priority
scoring still works.

Usage:
    python3 priority_classifier.py train      # train + save the ML model
    python3 priority_classifier.py test        # quick manual test

    from priority_classifier import classify_priority
    result = classify_priority("can't breathe help me")
    # -> {"priority": "CRITICAL", "score": 0.91, "backend": "ml"}
"""

import os
import re
import pickle

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "priority_model.pkl")

PRIORITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITY_ORDER)}  # 0 = most urgent

PRIORITY_COLORS = {
    "CRITICAL": "#D32F2F",   # red
    "HIGH":     "#F57C00",   # orange
    "MEDIUM":   "#FBC02D",   # yellow
    "LOW":      "#388E3C",   # green
    "UNKNOWN":  "#757575",   # gray
}

# ============================================================
# RULE-BASED FALLBACK  (always available, no dependencies)
# ============================================================
_CRITICAL_KEYWORDS = [
    "can't breathe", "cant breathe", "not breathing", "drowning", "fire",
    "bleeding heavily", "bleeding out", "chest pain", "heart attack",
    "unconscious", "not responding", "explosion", "gas leak",
    "losing consciousness", "paralyzed", "stabbed", "collapsed building",
    "collapsing", "no pulse", "choking", "seizure", "caving in",
    "severe burns",
]
_HIGH_KEYWORDS = [
    "trapped", "stuck under", "broken leg", "broken arm", "can't walk",
    "cant walk", "injured", "injury", "crash", "collapsed", "fell",
    "can't move", "cant move", "bleeding", "hurt", "locked in", "jammed",
    "pinned", "sprained", "getting worse",
]
_MEDIUM_KEYWORDS = [
    "cold", "hungry", "thirsty", "lost", "no food", "no water", "scared",
    "stranded", "alone", "dark", "tired", "supplies", "blanket",
    "phone dying", "waiting", "dehydrated", "medication", "no electricity",
    "no signal", "flooded",
]
_LOW_KEYWORDS = [
    "test", "checking", "hello", "confirm", "monitoring", "status update",
    "just letting you know", "not urgent", "all good", "everything okay",
    "false alarm", "nothing to report", "accounted for", "status normal",
]


def _rule_based_classify(text):
    """Transparent keyword-matching fallback. Highest-severity match wins."""
    t = text.lower()
    for kw in _CRITICAL_KEYWORDS:
        if kw in t:
            return {"priority": "CRITICAL", "score": 1.0, "backend": "rule",
                    "matched": kw}
    for kw in _HIGH_KEYWORDS:
        if kw in t:
            return {"priority": "HIGH", "score": 0.8, "backend": "rule",
                    "matched": kw}
    for kw in _MEDIUM_KEYWORDS:
        if kw in t:
            return {"priority": "MEDIUM", "score": 0.6, "backend": "rule",
                    "matched": kw}
    for kw in _LOW_KEYWORDS:
        if kw in t:
            return {"priority": "LOW", "score": 0.4, "backend": "rule",
                    "matched": kw}
    # No keyword matched: default to MEDIUM (better to over- than under-triage)
    return {"priority": "MEDIUM", "score": 0.5, "backend": "rule",
            "matched": None}


# ============================================================
# ML BACKEND  (TF-IDF + Logistic Regression)
# ============================================================
_ml_model = None
_ml_load_attempted = False


def _try_load_ml_model():
    """Lazy-load the trained model. Returns None if unavailable (no crash)."""
    global _ml_model, _ml_load_attempted
    if _ml_load_attempted:
        return _ml_model
    _ml_load_attempted = True
    try:
        if not os.path.exists(MODEL_PATH):
            return None
        with open(MODEL_PATH, "rb") as f:
            _ml_model = pickle.load(f)
        return _ml_model
    except Exception as e:
        print(f"⚠ Priority ML model failed to load ({e}) — using rule-based fallback")
        return None


def train_and_save_model():
    """Trains TF-IDF + Logistic Regression on training_data.py and saves it."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from training_data import TRAINING_DATA

    texts = [t for t, _ in TRAINING_DATA]
    labels = [l for _, l in TRAINING_DATA]

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    pipeline.fit(texts, labels)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"✓ Model trained on {len(texts)} examples, saved to {MODEL_PATH}")
    return pipeline


def _ml_classify(text):
    model = _try_load_ml_model()
    if model is None:
        return None
    try:
        pred = model.predict([text])[0]
        proba = model.predict_proba([text])[0]
        classes = list(model.classes_)
        score = float(proba[classes.index(pred)])
        return {"priority": pred, "score": score, "backend": "ml", "matched": None}
    except Exception as e:
        print(f"⚠ ML classification error ({e}) — using rule-based fallback")
        return None


# ============================================================
# PUBLIC API
# ============================================================

def classify_priority(text, backend="rule"):
    """
    Classify urgency of an SOS message.
    backend="rule" (default, RECOMMENDED for deployment): transparent,
        auditable keyword matching. No training needed, 100% offline,
        predictable failure mode (defaults to MEDIUM when unsure).
    backend="ml": TF-IDF + Logistic Regression. Included for research /
        comparison purposes; NOT recommended as the active system for a
        life-safety tool given the small seed dataset (see paper discussion).
    NEVER raises — always returns a usable result.
    """
    if not text or not text.strip():
        return {"priority": "UNKNOWN", "score": 0.0, "backend": "none", "matched": None}

    if backend == "ml":
        result = _ml_classify(text)
        if result is not None:
            return result
        # ML unavailable for any reason -> fall back to rules automatically
    return _rule_based_classify(text)


def priority_color(priority):
    return PRIORITY_COLORS.get(priority, PRIORITY_COLORS["UNKNOWN"])


def priority_rank(priority):
    """Lower = more urgent. Used for sorting the rescuer's SOS list."""
    return PRIORITY_RANK.get(priority, len(PRIORITY_ORDER))


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "train":
        train_and_save_model()

    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        test_messages = [
            "can't breathe help me please",
            "trapped under debris leg injured",
            "cold and hungry been here two days",
            "just checking if this works",
            "the building next to me is shaking and I smell smoke",
        ]
        for msg in test_messages:
            r_rule = classify_priority(msg, backend="rule")
            r_ml = classify_priority(msg, backend="ml")
            print(f"[rule] {r_rule['priority']:9s} (score={r_rule['score']:.2f})  "
                  f"[ml] {r_ml['priority']:9s} (score={r_ml['score']:.2f})  "
                  f"<- \"{msg}\"")
    else:
        print(__doc__)
