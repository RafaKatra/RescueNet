#!/usr/bin/env python3
"""
RescueNet - External (independent-corpus) triage evaluation
============================================================
Evaluates the *frozen* released triage code on data that the authors did not
write, label or tune against.  It answers the question "does the 200-message
result survive on messages the lexicon and the corpus were not built from?".

What is frozen
--------------
  * the 77-keyword rule tier of priority_classifier.py (not edited);
  * the TF-IDF (1-2 gram) + class-balanced logistic-regression model of
    eval_triage.py, fitted ONCE on the 200 synthetic messages of
    training_data.py and applied unchanged to the external data;
  * the hybrid (escalate to the higher of the two).
No external message is used for fitting, for the lexicon or for any choice
of threshold.  The tier-mapping below was fixed before any result was seen.

External sources (none is redistributed in this repository)
-----------------------------------------------------------
  A. Disaster Response messages (Appen / Figure Eight), "direct" genre only:
     first-person messages sent by people affected by the 2010 Haiti and
     Chile earthquakes, 2010 Pakistan floods and 2012 Hurricane Sandy, with
     English translations and 36 independent binary labels.
     Files: disaster_messages.csv, disaster_categories.csv
  B. CrisisLexT26 (Olteanu et al., 2015): labelled tweets of three events
     (Colorado wildfires 2012, Alberta floods 2013, Italy earthquakes 2012).
     Descriptive use only (no tier mapping): escalation rate by information
     type.  Files: <event>-tweets_labeled.csv
  C. SMS Spam Collection (UCI): irrelevant messages (spam and ordinary chat),
     used as a false-alarm check, not as a 4-class test.  File: sms.tsv

Pre-registered mapping of Appen labels to the four tiers (highest wins)
-----------------------------------------------------------------------
  CRITICAL : search_and_rescue
  HIGH     : medical_help or medical_products
  MEDIUM   : request, aid_related, water, food, shelter, clothing,
             missing_people, refugees, money or other_aid
  LOW      : none of the above (irrelevant or merely informative messages)
The Appen labels say what a message is *about*, not how urgent it is, and
they are crowd-sourced on translated text, so the mapping is an approximation
and the labels are noisy.  Results are therefore read as a robustness check,
not as field performance.

Usage
-----
  python3 eval_external.py --appen DIR --crisislex DIR --sms sms.tsv
where DIR for --appen holds disaster_messages.csv and disaster_categories.csv
and DIR for --crisislex holds the three *-tweets_labeled.csv files.
Any source may be omitted.  Fixed seeds; no network access.
"""
import argparse
import hashlib
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

import eval_triage as et
from priority_classifier import _rule_based_classify, PRIORITY_ORDER

RANK = et.RANK
N_PER_CLASS = 200          # balanced evaluation sample, comparable to Table 5
SEED = 42

CRIT = ["search_and_rescue"]
HIGH = ["medical_help", "medical_products"]
MED = ["request", "aid_related", "water", "food", "shelter", "clothing",
       "missing_people", "refugees", "money", "other_aid"]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]


def tier(row):
    if any(row[k] == 1 for k in CRIT):
        return "CRITICAL"
    if any(row[k] == 1 for k in HIGH):
        return "HIGH"
    if any(row[k] == 1 for k in MED):
        return "MEDIUM"
    return "LOW"


def load_appen(folder):
    m = pd.read_csv(os.path.join(folder, "disaster_messages.csv"))
    c = pd.read_csv(os.path.join(folder, "disaster_categories.csv"))
    cc = c["categories"].str.split(";", expand=True)
    names = [v.rsplit("-", 1)[0] for v in cc.iloc[0]]
    cc.columns = names
    for n in names:
        cc[n] = cc[n].str.rsplit("-", n=1).str[1].astype(int)
    cc["id"] = c["id"]
    d = m.merge(cc, on="id")
    d = d[d["genre"] == "direct"].copy()
    d["text"] = d["message"].astype(str).str.strip()
    d = d[d["text"].str.len() >= 3].drop_duplicates("text")
    d["true"] = d.apply(tier, axis=1)
    return d[["text", "true"]].reset_index(drop=True)


def predict_all(texts, model):
    rule = np.array([_rule_based_classify(t)["priority"] for t in texts], dtype=object)
    ml = model.predict(np.array(texts, dtype=object)).astype(object)
    hyb = et.hybrid(rule, ml)
    unmatched = np.array([_rule_based_classify(t)["matched"] is None for t in texts])
    return {"rule": rule, "ml": ml, "hybrid": hyb}, unmatched


def metrics(y, pred):
    y = np.asarray(y, dtype=object)
    out = {
        "acc": float((pred == y).mean()),
        "mF1": float(f1_score(y, pred, average="macro", labels=PRIORITY_ORDER)),
        "over": int(sum(RANK[p] < RANK[t] for p, t in zip(pred, y))),
        "under": int(sum(RANK[p] > RANK[t] for p, t in zip(pred, y))),
    }
    for c in PRIORITY_ORDER:
        idx = y == c
        out["rec_" + c] = float((pred[idx] == c).mean()) if idx.any() else float("nan")
    return out


def boot_ci(y, pred, cls="CRITICAL", n=2000, seed=SEED):
    """Stratified bootstrap 95% CI for the recall of one class."""
    y = np.asarray(y, dtype=object)
    rng = np.random.default_rng(seed)
    idx = np.where(y == cls)[0]
    vals = [(pred[rng.choice(idx, len(idx), replace=True)] == cls).mean() for _ in range(n)]
    return tuple(float(v) for v in np.percentile(vals, [2.5, 97.5]))


def report_block(title, y, preds, unmatched=None):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    print(f"{'config':8s} {'acc':>6s} {'mF1':>6s} {'critRec':>8s} {'crit 95% CI':>14s} "
          f"{'over':>5s} {'under':>6s}   recall C / H / M / L")
    for k in ("rule", "ml", "hybrid"):
        m = metrics(y, preds[k])
        lo, hi = boot_ci(y, preds[k])
        print(f"{k:8s} {m['acc']:6.3f} {m['mF1']:6.3f} {m['rec_CRITICAL']:8.3f} "
              f"[{lo:.2f}, {hi:.2f}] {m['over']:5d} {m['under']:6d}   "
              f"{m['rec_CRITICAL']:.2f} / {m['rec_HIGH']:.2f} / {m['rec_MEDIUM']:.2f} / {m['rec_LOW']:.2f}")
    yy = np.asarray(y, dtype=object)
    ci = yy == "CRITICAL"
    b, c, p = et.mcnemar_exact(preds["hybrid"][ci] == "CRITICAL", preds["ml"][ci] == "CRITICAL")
    print(f"McNemar critical recall (hybrid vs ml): hybrid-only={b} ml-only={c} p={p:.3g}")
    b, c, p = et.mcnemar_exact(preds["hybrid"][ci] == "CRITICAL", preds["rule"][ci] == "CRITICAL")
    print(f"McNemar critical recall (hybrid vs rule): hybrid-only={b} rule-only={c} p={p:.3g}")
    if unmatched is not None:
        print(f"messages matching no keyword (rule tier -> MEDIUM default): {unmatched.mean():.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appen")
    ap.add_argument("--crisislex")
    ap.add_argument("--sms")
    a = ap.parse_args()

    # Freeze: fit the learned model once, on the 200 synthetic messages only.
    model = et.word_pipe().fit(et.X, et.y)
    print("Frozen configuration: rule lexicon + TF-IDF/LR fitted on the 200 "
          f"synthetic messages (training_data.py sha {sha('training_data.py')}, "
          f"priority_classifier.py sha {sha('priority_classifier.py')})")

    if a.appen:
        d = load_appen(a.appen)
        print(f"\n[Appen direct messages] n={len(d)} after de-duplication; "
              f"mapped tiers: {d['true'].value_counts().to_dict()}")
        # (i) class-balanced sample, comparable to Table 5
        rng = np.random.default_rng(SEED)
        parts = [d[d.true == c].sample(n=min(N_PER_CLASS, (d.true == c).sum()),
                                       random_state=SEED) for c in PRIORITY_ORDER]
        bal = pd.concat(parts).reset_index(drop=True)
        preds, un = predict_all(list(bal.text), model)
        report_block(f"A1. Appen direct messages, balanced sample "
                     f"({', '.join(f'{c}={int((bal.true==c).sum())}' for c in PRIORITY_ORDER)})",
                     bal.true.values, preds, un)
        # (ii) full natural distribution
        preds, un = predict_all(list(d.text), model)
        report_block(f"A2. Appen direct messages, natural distribution (n={len(d)})",
                     d.true.values, preds, un)
        # ---- Post-hoc, exploratory (defined AFTER the primary results were seen) ----
        # (a) Taxonomy-consistent coarse view.  In the released tier definitions a
        # person trapped or injured is HIGH, not CRITICAL, so the finest mapping above
        # is harsh on search-and-rescue messages.  Collapse to "life-safety" =
        # CRITICAL or HIGH (search_and_rescue / medical) versus everything else.
        print("\n" + "-" * 78)
        print("A3 [post-hoc]. Life-safety view on the natural distribution: a message is")
        print("   'life-safety' if mapped to CRITICAL or HIGH; a prediction 'escalates' if it")
        print("   is CRITICAL or HIGH.")
        print("-" * 78)
        pn, _ = predict_all(list(d.text), model)
        ls = d.true.isin(["CRITICAL", "HIGH"]).values
        print(f"life-safety n={int(ls.sum())}, other n={int((~ls).sum())}")
        print(f"{'config':8s} {'recall(life-safety)':>20s} {'false escalation':>18s}")
        for k in ("rule", "ml", "hybrid"):
            esc = np.isin(pn[k], ["CRITICAL", "HIGH"])
            print(f"{k:8s} {esc[ls].mean():20.3f} {esc[~ls].mean():18.3f}")
        # (b) Capacity of the *approach* when trained on realistic data (5-fold CV
        # on the balanced Appen sample) and transfer in the opposite direction.
        print("\n" + "-" * 78)
        print("A4 [post-hoc]. Same TF-IDF/LR pipeline trained on Appen (5-fold CV on the")
        print("   balanced sample) and trained on Appen, tested on the 200 synthetic messages")
        print("-" * 78)
        from sklearn.model_selection import StratifiedKFold
        Xb = np.array(list(bal.text), dtype=object); yb = bal.true.values.astype(object)
        mlp = np.empty(len(yb), dtype=object)
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=SEED).split(Xb, yb):
            mlp[te] = et.word_pipe().fit(Xb[tr], yb[tr]).predict(Xb[te])
        rb = np.array([_rule_based_classify(t)["priority"] for t in Xb], dtype=object)
        for nm, pr in (("ml (CV on Appen)", mlp), ("hybrid (rule + that ml)", et.hybrid(rb, mlp))):
            m = metrics(yb, pr); lo, hi = boot_ci(yb, pr)
            print(f"{nm:24s} acc={m['acc']:.3f} mF1={m['mF1']:.3f} critRec={m['rec_CRITICAL']:.3f} [{lo:.2f},{hi:.2f}]")
        back = et.word_pipe().fit(Xb, yb).predict(et.X).astype(object)
        m = metrics(et.y, back)
        print(f"{'train Appen -> test synthetic 200':24s} acc={m['acc']:.3f} mF1={m['mF1']:.3f} critRec={m['rec_CRITICAL']:.3f}")
        # confusion matrix of the hybrid on the balanced sample
        p2, _ = predict_all(list(bal.text), model)
        print("\nHybrid confusion matrix, balanced sample (rows true, cols predicted)")
        cm = pd.crosstab(bal.true, pd.Series(p2["hybrid"], name="pred"))
        print(cm.reindex(index=PRIORITY_ORDER, columns=PRIORITY_ORDER, fill_value=0).to_string())

    if a.crisislex:
        print("\n" + "=" * 78)
        print("B. CrisisLexT26 tweets - share escalated to CRITICAL/HIGH, by information type")
        print("=" * 78)
        frames = []
        for f in sorted(os.listdir(a.crisislex)):
            if f.endswith("-tweets_labeled.csv"):
                t = pd.read_csv(os.path.join(a.crisislex, f), skipinitialspace=True)
                t["event"] = f.replace("-tweets_labeled.csv", "")
                frames.append(t)
        t = pd.concat(frames)
        t = t[t["Information Type"].notna()].copy()
        texts = list(t["Tweet Text"].astype(str))
        preds, un = predict_all(texts, model)
        for k in ("rule", "ml", "hybrid"):
            t["esc_" + k] = np.isin(preds[k], ["CRITICAL", "HIGH"])
        g = t.groupby("Information Type")[["esc_rule", "esc_ml", "esc_hybrid"]].mean().round(3)
        g["n"] = t.groupby("Information Type").size()
        print(g.sort_values("esc_hybrid", ascending=False).to_string())
        aff = t["Information Type"] == "Affected individuals"
        oth = t["Information Type"].isin(["Sympathy and support", "Not labeled"]) | \
            (t["Informativeness"] == "Not related")
        print(f"\n'Affected individuals' (n={int(aff.sum())}) vs sympathy/unrelated (n={int(oth.sum())})")
        for k in ("rule", "ml", "hybrid"):
            print(f"  {k:7s} escalated: {t.loc[aff, 'esc_'+k].mean():.3f} vs {t.loc[oth, 'esc_'+k].mean():.3f}")

    if a.sms:
        s = pd.read_csv(a.sms, sep="\t", header=None, names=["label", "text"])
        print("\n" + "=" * 78)
        print("C. SMS Spam Collection - irrelevant messages (false-alarm check)")
        print("=" * 78)
        for lab in ("spam", "ham"):
            texts = list(s[s.label == lab].text.astype(str))
            preds, un = predict_all(texts, model)
            print(f"\n{lab} (n={len(texts)})   share assigned CRITICAL / HIGH / MEDIUM / LOW")
            for k in ("rule", "ml", "hybrid"):
                v = pd.Series(preds[k]).value_counts(normalize=True)
                print(f"  {k:7s} " + " / ".join(f"{v.get(c, 0):.3f}" for c in PRIORITY_ORDER))


if __name__ == "__main__":
    main()
