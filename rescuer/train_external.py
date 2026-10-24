#!/usr/bin/env python3
"""
RescueNet - Train and evaluate the triage model on independent, realistic data
===============================================================================
Companion to eval_external.py.  Where eval_external.py *freezes* the released
model (trained on the 200 synthetic messages) and tests it on foreign data,
this script trains the SAME TF-IDF (1-2 gram) + class-balanced logistic
regression pipeline on real disaster-response messages and measures what that
buys, under a protocol that keeps train, selection and test separate.

Data (not redistributed here; CC BY 4.0, Robert Munro / Appen)
---------------------------------------------------------------
  https://github.com/rmunro/disaster_response_messages
  disaster_response_training.csv / _validation.csv / _test.csv  (official splits)
Only the "direct" genre is used: first-person messages from people affected by
the 2010 Haiti earthquake, the 2010 Pakistan floods and Hurricane Sandy 2012,
with English translations.  News headlines are excluded (wrong register).
Messages are mapped to the four RescueNet tiers with the same fixed rule as
eval_external.py (search_and_rescue -> CRITICAL; medical_help/medical_products
-> HIGH; request/aid_* -> MEDIUM; otherwise LOW).  The labels describe what a
message is about, not its urgency, and are crowd-sourced on translated text, so
the mapping is an approximation.

Protocol
--------
  * fit on the official training split only;
  * the single hyper-parameter (C of the logistic regression, grid fixed in
    advance) is chosen on the validation split by macro-F1;
  * the official test split is used once, for the final numbers;
  * messages identical to a training message are removed from validation/test;
  * an event-held-out check trains on Haiti + Pakistan and tests on Sandy;
  * the rule lexicon is the frozen released one (priority_classifier.py).

Usage
-----
  python3 train_external.py --drm DIR [--sms spam.csv] [--crisislex DIR]
                            [--save priority_model.pkl]
DIR holds the three disaster_response_*.csv files.  --save writes the model
fitted on training+validation in the pickle format priority_classifier.py loads.
"""
import argparse
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline

import eval_triage as et
from eval_external import tier, metrics, boot_ci
from priority_classifier import _rule_based_classify, PRIORITY_ORDER

SEED = 42
C_GRID = [0.1, 0.3, 1, 3, 10, 30]
RANK = et.RANK


def load_split(folder, name):
    d = pd.read_csv(os.path.join(folder, f"disaster_response_{name}.csv"), low_memory=False)
    d = d[d["genre"] == "direct"].copy()
    d["text"] = d["message"].astype(str).str.strip()
    d = d[d["text"].str.len() >= 3].drop_duplicates("text")
    d["true"] = d.apply(tier, axis=1)
    return d[["text", "true", "event"]].reset_index(drop=True)


def pipe(C=1.0):
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=True)),
        ("clf", LogisticRegression(max_iter=2000, C=C, class_weight="balanced")),
    ])


def rule(texts):
    return np.array([_rule_based_classify(t)["priority"] for t in texts], dtype=object)


def rule_full(texts):
    """Rule tier output plus whether any keyword matched."""
    out = [_rule_based_classify(t) for t in texts]
    return (np.array([o["priority"] for o in out], dtype=object),
            np.array([o["matched"] is not None for o in out]))


def hybrid_matched(texts, ml_pred):
    """Escalate to the higher of rule and model, but let the rule tier vote only
    when it actually matched a keyword; an unmatched message keeps the model's
    decision instead of the rule tier's MEDIUM default."""
    r, m = rule_full(texts)
    return np.array([min(rp, mp, key=lambda z: RANK[z]) if hit else mp
                     for rp, mp, hit in zip(r, ml_pred, m)], dtype=object)


def ls_ci(y, pred, n=2000, seed=SEED):
    """Bootstrap 95% CI of life-safety recall (CRITICAL or HIGH escalated)."""
    ls = np.where(np.isin(y, ["CRITICAL", "HIGH"]))[0]
    esc = np.isin(pred, ["CRITICAL", "HIGH"])
    rng = np.random.default_rng(seed)
    v = [esc[rng.choice(ls, len(ls), replace=True)].mean() for _ in range(n)]
    return tuple(float(x) for x in np.percentile(v, [2.5, 97.5]))


def life_safety(y, pred):
    ls = np.isin(y, ["CRITICAL", "HIGH"])
    esc = np.isin(pred, ["CRITICAL", "HIGH"])
    return float(esc[ls].mean()), float(esc[~ls].mean())


def block(title, y, configs):
    y = np.asarray(y, dtype=object)
    print("\n" + "=" * 86)
    print(title + f"   (n={len(y)}: " +
          ", ".join(f"{c}={int((y == c).sum())}" for c in PRIORITY_ORDER) + ")")
    print("=" * 86)
    print(f"{'configuration':34s} {'acc':>5s} {'mF1':>5s} {'critRec':>8s} {'95% CI':>12s} "
          f"{'C/H/M/L recall':>20s} {'LS-recall [95% CI]':>19s} {'FalseEsc':>8s}")
    for name, pr in configs:
        m = metrics(y, pr); lo, hi = boot_ci(y, pr)
        ls, fe = life_safety(y, pr); l1, l2 = ls_ci(y, pr)
        print(f"{name:34s} {m['acc']:5.3f} {m['mF1']:5.3f} {m['rec_CRITICAL']:8.3f} "
              f"[{lo:.2f},{hi:.2f}] {m['rec_CRITICAL']:.2f}/{m['rec_HIGH']:.2f}/"
              f"{m['rec_MEDIUM']:.2f}/{m['rec_LOW']:.2f}   {ls:5.3f} [{l1:.2f},{l2:.2f}] {fe:7.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drm", required=True)
    ap.add_argument("--sms")
    ap.add_argument("--crisislex")
    ap.add_argument("--save")
    a = ap.parse_args()

    tr = load_split(a.drm, "training")
    va = load_split(a.drm, "validation")
    te = load_split(a.drm, "test")
    seen = set(tr.text)
    va = va[~va.text.isin(seen)].reset_index(drop=True)
    te = te[~te.text.isin(seen | set(va.text))].reset_index(drop=True)
    print(f"direct messages  train={len(tr)}  validation={len(va)}  test={len(te)}")
    print("train tiers:", tr.true.value_counts().to_dict())

    # --- choose C on validation ---------------------------------------------------
    best = None
    print("\nValidation (macro-F1) for the fixed C grid:")
    for C in C_GRID:
        p = pipe(C).fit(tr.text.values, tr.true.values)
        f1 = f1_score(va.true.values, p.predict(va.text.values), average="macro", labels=PRIORITY_ORDER)
        print(f"  C={C:<5} macro-F1={f1:.3f}")
        if best is None or f1 > best[0]:
            best = (f1, C)
    C = best[1]
    print(f"selected C={C}")

    model = pipe(C).fit(tr.text.values, tr.true.values)
    # same corpus + the 200 synthetic messages
    syn = pipe(C).fit(np.concatenate([tr.text.values, et.X]),
                      np.concatenate([tr.true.values.astype(object), et.y]))
    frozen = et.word_pipe().fit(et.X, et.y)     # released model (synthetic only)

    # --- final test ---------------------------------------------------------------
    X = te.text.values; y = te.true.values
    r = rule(X)
    ml_f = frozen.predict(X).astype(object); ml_n = model.predict(X).astype(object)
    ml_s = syn.predict(X).astype(object)
    block("TEST split (official), natural distribution", y, [
        ("rule tier (released)", r),
        ("ML trained on synthetic 200", ml_f),
        ("hybrid: rule + synthetic ML", et.hybrid(r, ml_f)),
        ("ML trained on real messages", ml_n),
        ("hybrid: rule + real-trained ML", et.hybrid(r, ml_n)),
        ("ML trained on real + synthetic", ml_s),
        ("hybrid-matched: rule* + real ML", hybrid_matched(X, ml_n)),
        ("hybrid-matched: rule* + real+syn ML", hybrid_matched(X, ml_s)),
    ])
    # class-balanced view of the same test split (comparable to Table 5)
    n = int(min((te.true == c).sum() for c in PRIORITY_ORDER))
    bal = pd.concat([te[te.true == c].sample(n=n, random_state=SEED) for c in PRIORITY_ORDER])
    Xb = bal.text.values; yb = bal.true.values; rb = rule(Xb)
    mf = frozen.predict(Xb).astype(object); mn = model.predict(Xb).astype(object)
    block("TEST split, class-balanced subsample", yb, [
        ("rule tier (released)", rb),
        ("ML trained on synthetic 200", mf),
        ("hybrid: rule + synthetic ML", et.hybrid(rb, mf)),
        ("ML trained on real messages", mn),
        ("hybrid: rule + real-trained ML", et.hybrid(rb, mn)),
        ("hybrid-matched: rule* + real ML", hybrid_matched(Xb, mn)),
    ])

    # --- event held out: train Haiti + Pakistan, test Sandy ------------------------
    allv = pd.concat([tr, va, te]).drop_duplicates("text")
    trn = allv[allv.event.isin(["haiti_earthquake", "pakistan_floods"])]
    sandy = allv[allv.event == "usa_sandy"]
    if len(sandy):
        m2 = pipe(C).fit(trn.text.values, trn.true.values)
        Xs = sandy.text.values; ys = sandy.true.values; rs = rule(Xs)
        mfs = frozen.predict(Xs).astype(object); mns = m2.predict(Xs).astype(object)
        block("Event held out: trained on Haiti+Pakistan, tested on Hurricane Sandy", ys, [
            ("rule tier (released)", rs),
            ("ML trained on synthetic 200", mfs),
            ("hybrid: rule + synthetic ML", et.hybrid(rs, mfs)),
            ("ML trained on Haiti+Pakistan", mns),
            ("hybrid: rule + that ML", et.hybrid(rs, mns)),
            ("hybrid-matched: rule* + that ML", hybrid_matched(Xs, mns)),
        ])

    # --- field messages of the paper (Tables 4 and 6) ------------------------------
    field = [("Help", "MEDIUM"), ("I am bleeding", "HIGH"), ("Water flooding", "MEDIUM"),
             ("I have injured please help", "HIGH"), ("I am trapped", "HIGH"),
             ("There is fire, behind please come", "CRITICAL"), ("There is fire here", "CRITICAL"),
             ("I can't breathe smoke everywhere please help", "CRITICAL"),
             ("lost", "MEDIUM")]
    print("\nPaper field messages: intended | rule | synthetic ML | real ML | real+syn ML | hybrid-matched(real+syn)")
    ok = [0] * 5
    for t, want in field:
        rr = _rule_based_classify(t)["priority"]; f = frozen.predict([t])[0]
        n_ = model.predict([t])[0]; s_ = syn.predict([t])[0]
        h = hybrid_matched([t], np.array([s_], dtype=object))[0]
        for i, v in enumerate((rr, f, n_, s_, h)):
            ok[i] += v == want
        print(f"  {t[:42]:42s} {want:9s} {rr:9s} {f:9s} {n_:9s} {s_:9s} {h}")
    print(f"  correct of {len(field)}: rule {ok[0]}, synthetic ML {ok[1]}, real ML {ok[2]}, "
          f"real+syn ML {ok[3]}, hybrid-matched {ok[4]}")

    # --- does adding real data keep the synthetic-corpus performance? --------------
    from sklearn.model_selection import StratifiedKFold
    pred = np.empty(len(et.y), dtype=object)
    for tr_i, te_i in StratifiedKFold(5, shuffle=True, random_state=SEED).split(et.X, et.y):
        p_ = pipe(C).fit(np.concatenate([tr.text.values, et.X[tr_i]]),
                         np.concatenate([tr.true.values.astype(object), et.y[tr_i]]))
        pred[te_i] = p_.predict(et.X[te_i])
    ru = rule(et.X)
    ru_m, hit = rule_full(et.X)
    hm = np.array([min(a_, b_, key=lambda z: RANK[z]) if h_ else b_ for a_, b_, h_ in zip(ru_m, pred, hit)], dtype=object)
    print("\nSynthetic 200-message corpus, 5-fold CV (real data always in training; synthetic folds held out)")
    for nm, pr in (("ML real + synthetic(train folds)", pred), ("hybrid-matched", hm)):
        m = metrics(et.y, pr); lo, hi = boot_ci(et.y, pr)
        print(f"  {nm:34s} acc={m['acc']:.3f} mF1={m['mF1']:.3f} critRec={m['rec_CRITICAL']:.3f} [{lo:.2f},{hi:.2f}] over={m['over']} under={m['under']}")

    # --- irrelevant messages --------------------------------------------------------
    if a.sms:
        s = pd.read_csv(a.sms, encoding="latin-1").iloc[:, :2]
        s.columns = ["label", "text"]
        print("\nSMS Spam Collection - share assigned CRITICAL / HIGH / MEDIUM / LOW")
        for lab in ("spam", "ham"):
            t = s[s.label == lab].text.astype(str).values
            for nm, pr in (("rule", rule(t)), ("synthetic ML", frozen.predict(t)),
                           ("real-trained ML", model.predict(t)),
                           ("real+syn ML", syn.predict(t))):
                v = pd.Series(pr).value_counts(normalize=True)
                print(f"  {lab:4s} {nm:16s} " + " / ".join(f"{v.get(c, 0):.3f}" for c in PRIORITY_ORDER))

    # --- tweets, descriptive --------------------------------------------------------
    if a.crisislex:
        fr = []
        for f in sorted(os.listdir(a.crisislex)):
            if f.endswith("-tweets_labeled.csv"):
                fr.append(pd.read_csv(os.path.join(a.crisislex, f), skipinitialspace=True))
        t = pd.concat(fr); t = t[t["Information Type"].notna()]
        txt = t["Tweet Text"].astype(str).values
        t["esc_syn"] = np.isin(frozen.predict(txt), ["CRITICAL", "HIGH"])
        t["esc_real"] = np.isin(model.predict(txt), ["CRITICAL", "HIGH"])
        aff = t["Information Type"] == "Affected individuals"
        oth = t["Information Type"].isin(["Sympathy and support", "Not labeled"]) | (t["Informativeness"] == "Not related")
        print("\nCrisisLexT26 tweets - escalated to CRITICAL/HIGH: 'Affected individuals' vs sympathy/unrelated")
        for k in ("esc_syn", "esc_real"):
            print(f"  {k:9s} {t.loc[aff, k].mean():.3f} vs {t.loc[oth, k].mean():.3f}  "
                  f"(n={int(aff.sum())}/{int(oth.sum())})")

    if a.save:
        full = pd.concat([tr, va])
        final = pipe(C).fit(full.text.values, full.true.values)
        with open(a.save, "wb") as f:
            pickle.dump(final, f)
        print(f"\nmodel fitted on training+validation ({len(full)} messages) saved to {a.save}")


if __name__ == "__main__":
    main()
