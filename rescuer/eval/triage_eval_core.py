#!/usr/bin/env python3
# Evaluation copy of the rule tier and ML pipeline of rescuer/priority_classifier.py (identical lexicon and settings; verified to give identical rule decisions on the 200-message corpus).
import os, re, pickle

PRIORITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITY_ORDER)}

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


def rule_classify(text):
    t = text.lower()
    for kws, p in ((_CRITICAL_KEYWORDS, "CRITICAL"), (_HIGH_KEYWORDS, "HIGH"),
                   (_MEDIUM_KEYWORDS, "MEDIUM"), (_LOW_KEYWORDS, "LOW")):
        for kw in kws:
            if kw in t:
                return p
    return "MEDIUM"


def make_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
