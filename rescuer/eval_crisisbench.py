#!/usr/bin/env python3
"""
External validation on CrisisBench (Alam et al., ICWSM 2021), English
"humanitarian" task: ~87k human-labelled crisis tweets drawn from CrisisLexT6,
CrisisLexT26, CrisisNLP, CrisisMMD, AIDR and others, with official
train/dev/test splits.  Data are NOT redistributed here; download
all_data_en from https://crisisnlp.qcri.org/crisis_datasets_benchmarks

Usage (from rescuer/):
    python eval_crisisbench.py --data DIR_WITH_all_data_en_TSVs

PRE-REGISTERED TARGET (fixed before any model was run on these data)
  positive  ("needs a responder's attention"):
            requests_or_needs, injured_or_dead_people, missing_and_found_people
  negative  : not_humanitarian, sympathy_and_support, donation_and_volunteering,
            caution_and_advice, response_efforts
  excluded  : affected_individual, infrastructure_and_utilities_damage,
            displaced_and_evacuations (ambiguous with respect to urgency)
  A prediction "escalates" if the tier is CRITICAL or HIGH.
  Metrics: recall of positives (escalation rate) and false-escalation rate on
  negatives, with 95% bootstrap CIs; macro-F1 of the binary decision.

IMPORTANT LIMITATIONS (to be reported with the results)
  * Most items are third-party reports (news, retweets), not first-person SOS
    messages; the target is therefore a proxy for the paper's triage task.
  * The label mapping is ours, not the annotators'.
  * English only.

Configurations
  frozen-rule / frozen-ml / frozen-hybrid : released configuration, fitted on
      the 200 synthetic messages only, never touched.
  retrained-ml : TF-IDF(1-2gram)+class-balanced LogReg fitted on CrisisBench
      train; C selected on dev.
  retrained+rule : retrained-ml OR rule tier (rule votes only if a keyword
      matched).
  Event-held-out: for each event family F, train on train+dev of all other
      families, test on the test split of F.
"""
import argparse
import os
import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline

import eval_triage as et
from priority_classifier import _rule_based_classify

SEED = 42
C_GRID = [0.1, 0.3, 1, 3, 10, 30]
POS = {"requests_or_needs", "injured_or_dead_people", "missing_and_found_people"}
NEG = {"not_humanitarian", "sympathy_and_support", "donation_and_volunteering",
       "caution_and_advice", "response_efforts"}
FAMILIES = [
    ("wildfire", r"wildfire|bushfire|fire"),
    ("bombing/explosion", r"bomb|explosion|refinery"),
    ("shooting", r"shooting"),
    ("earthquake", r"earthquake"),
    ("flood", r"flood"),
    ("storm", r"tornado|hurricane|typhoon|cyclone|sandy|storm"),
]


def family(ev):
    ev = str(ev).lower()
    for name, pat in FAMILIES:
        if re.search(pat, ev):
            return name
    return "other"


def load(folder, split):
    f = os.path.join(folder, f"crisis_consolidated_humanitarian_filtered_lang_en_{split}.tsv")
    d = pd.read_csv(f, sep="\t", quoting=3, on_bad_lines="skip")
    d = d[d.class_label.isin(POS | NEG)].copy()
    d["text"] = d.text.astype(str).str.strip()
    d = d[d.text.str.len() >= 3].drop_duplicates("text")
    d["y"] = d.class_label.isin(POS).astype(int)
    d["fam"] = d.event.map(family)
    return d.reset_index(drop=True)


def esc(pred):
    return np.isin(pred, ["CRITICAL", "HIGH"]).astype(int)


def rule_out(texts):
    o = [_rule_based_classify(t) for t in texts]
    return (np.array([x["priority"] for x in o], dtype=object),
            np.array([x["matched"] is not None for x in o]))


def boot(y, e, which, n=1000):
    rng = np.random.default_rng(SEED)
    idx = np.where(y == which)[0]
    if len(idx) == 0:
        return (float("nan"),) * 2
    v = [e[rng.choice(idx, len(idx))].mean() for _ in range(n)]
    return tuple(np.percentile(v, [2.5, 97.5]))


def row(name, y, e):
    y = np.asarray(y)
    rec = e[y == 1].mean() if (y == 1).any() else float("nan")
    fa = e[y == 0].mean() if (y == 0).any() else float("nan")
    l1, l2 = boot(y, e, 1)
    f1 = f1_score(y, e, average="macro") if len(set(y)) > 1 else float("nan")
    print(f"  {name:28s} recall {rec:5.3f} [{l1:.2f},{l2:.2f}]  false-esc {fa:5.3f}  macroF1 {f1:5.3f}")


def pipe(C):
    return Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)),
                     ("clf", LogisticRegression(max_iter=2000, C=C, class_weight="balanced"))])


def fit_best(tr, dv):
    best = None
    for C in C_GRID:
        m = pipe(C).fit(tr.text, tr.y)
        f = f1_score(dv.y, m.predict(dv.text), average="macro")
        if best is None or f > best[0]:
            best = (f, C, m)
    return best


def configs(texts, frozen, retrained):
    r, hit = rule_out(texts)
    fz_ml = frozen.predict(np.array(texts, dtype=object)).astype(object)
    fz_h = et.hybrid(r, fz_ml)
    rt = retrained.predict(texts).astype(int)
    return [("frozen-rule", esc(r)), ("frozen-ml", esc(fz_ml)), ("frozen-hybrid", esc(fz_h)),
            ("retrained-ml", rt),
            ("retrained+rule(matched)", np.maximum(rt, esc(r) * hit))]


def report(title, d, frozen, retrained):
    y = d.y.values
    print(f"\n{title}  (n={len(d)}; positives={int(y.sum())}, negatives={int((y == 0).sum())})")
    for name, e in configs(list(d.text), frozen, retrained):
        row(name, y, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    tr, dv, te = (load(a.data, s) for s in ("train", "dev", "test"))
    # remove test texts that also occur in train/dev (leakage by retweets)
    seen = set(tr.text) | set(dv.text)
    te = te[~te.text.isin(seen)].reset_index(drop=True)
    print(f"train {len(tr)}  dev {len(dv)}  test {len(te)} (after de-duplication against train/dev)")
    print("test families:", te.fam.value_counts().to_dict())

    frozen = et.word_pipe().fit(et.X, et.y)
    f, C, retrained = fit_best(tr, dv)
    print(f"retrained: C={C} chosen on dev (macro-F1 {f:.3f})")

    print("\n" + "=" * 90 + "\nA. Official test split, all events")
    report("A. all events", te, frozen, retrained)
    print("\n" + "=" * 90 + "\nB. Per event family (same models; retrained saw these families in training)")
    for fam, g in te.groupby("fam"):
        if len(g) >= 50:
            report(f"B. {fam}", g.reset_index(drop=True), frozen, retrained)

    print("\n" + "=" * 90 + "\nC. Event-family held out (retrained on all OTHER families)")
    full = pd.concat([tr, dv]).reset_index(drop=True)
    for fam in ("wildfire", "bombing/explosion", "shooting", "earthquake", "flood"):
        g = te[te.fam == fam].reset_index(drop=True)
        if len(g) < 50:
            print(f"\nC. {fam}: only {len(g)} test items, skipped")
            continue
        if (g.y == 1).sum() < 15:
            print(f"\nC. {fam}: {int((g.y == 1).sum())} positives -> recall not estimable; "
                  "only the false-escalation rate is meaningful")
        rest = full[full.fam != fam]
        m = pipe(1.0).fit(rest.text, rest.y)       # C=1, no tuning on the held-out family
        report(f"C. held out: {fam}", g, frozen, m)


if __name__ == "__main__":
    main()
