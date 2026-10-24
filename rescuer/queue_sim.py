#!/usr/bin/env python3
"""
RescueNet - Single-hub load simulation (paper Section 3.4, Figure 6)
=====================================================================
The hub LoRa radio relays one report at a time. This Monte-Carlo simulation
models a HYPOTHETICAL single-hub transmit queue (not implemented in the
released hub, which transmits each report inline, first come first served)
to quantify what transmission ordering could and could not achieve for the
delay of CRITICAL reports under a burst.

Model
-----
  * N reports (20 or 50).
  * Each report is assigned a TRUE urgency class from an assumed field-like
    skew: 10% CRITICAL, 20% HIGH, 40% MEDIUM, 30% LOW (not the balanced
    corpus mix).
  * Each report is assigned a PREDICTED priority by sampling from the
    empirical out-of-sample confusion distribution P(pred | true) of the
    corresponding configuration of Table 5 (rule / hybrid), measured by the
    five-fold cross-validation of eval_triage.py.
  * Airtime is a fixed 5.6 s per report (148-byte encrypted report at SF12,
    paper Table 3), back-to-back.
  * Arrivals are either all at t=0 ("simultaneous") or spread uniformly over
    600 s ("over ten minutes").

Queue disciplines
-----------------
  FCFS    : arrival order (the released hub's behaviour).
  rule    : by predicted priority of the rule tier, then arrival.
  hybrid  : by predicted priority of the hybrid, then arrival.
  oracle  : by TRUE class, then arrival (upper bound on any classifier).

A report is "relayed" when its airtime finishes; its delay is
relay_time - arrival_time. We report the median and 90th percentile of that
delay over CRITICAL reports, pooled across all Monte-Carlo runs.

Usage:  python3 queue_sim.py            # prints the Section 3.4 figures
        python3 queue_sim.py --plot     # also writes figure6_queue.png (Figure 6)
"""
import sys
import numpy as np
from eval_triage import cv_predict, rule_predict, hybrid, word_pipe, y, PRIORITY_ORDER

AIRTIME = 5.6
SKEW = {"CRITICAL": 0.10, "HIGH": 0.20, "MEDIUM": 0.40, "LOW": 0.30}
RANK = {p: i for i, p in enumerate(PRIORITY_ORDER)}


def confusion_rows(pred):
    """P(pred | true) as a dict: true_class -> (labels, probabilities)."""
    rows = {}
    for c in PRIORITY_ORDER:
        preds = pred[y == c]
        labels, counts = np.unique(preds, return_counts=True)
        rows[c] = (labels, counts / counts.sum())
    return rows


def simulate(n, arrival, conf_rows, rng, runs=4000):
    """Return pooled CRITICAL delays for each discipline over `runs` runs."""
    classes = list(SKEW)
    probs = [SKEW[c] for c in classes]
    out = {d: [] for d in ("fcfs", "rule", "hybrid", "oracle")}
    for _ in range(runs):
        true = rng.choice(classes, size=n, p=probs)
        if arrival == "sim":
            arr = np.zeros(n)
        else:  # uniform over 600 s
            arr = rng.uniform(0, 600, size=n)
        # predicted priority per discipline, sampled from the confusion rows
        p_rule = np.array([_draw(conf_rows["rule"], t, rng) for t in true], dtype=object)
        p_hyb = np.array([_draw(conf_rows["hybrid"], t, rng) for t in true], dtype=object)

        keys = {
            "fcfs":   np.array([0]*n),
            "rule":   np.array([RANK[p] for p in p_rule]),
            "hybrid": np.array([RANK[p] for p in p_hyb]),
            "oracle": np.array([RANK[t] for t in true]),
        }
        crit = (true == "CRITICAL")
        for d, key in keys.items():
            relay = _serve(arr, key, n)
            delay = relay - arr
            out[d].extend(delay[crit].tolist())
    return {d: np.array(v) for d, v in out.items()}


def _draw(conf, true_class, rng):
    labels, p = conf[true_class]
    return rng.choice(labels, p=p)



def _serve(arr, key, n):
    """Event-driven single server: at each completion, serve the waiting
    report with the smallest (key, arrival). Server idles until a report is
    available. Returns relay-completion time per report."""
    relay = np.empty(n)
    done = np.zeros(n, dtype=bool)
    t = 0.0
    order_arr = np.argsort(arr, kind="stable")
    for _ in range(n):
        avail = [j for j in order_arr if not done[j] and arr[j] <= t]
        if not avail:
            nxt = min(arr[j] for j in range(n) if not done[j])
            t = nxt
            avail = [j for j in order_arr if not done[j] and arr[j] <= t]
        j = min(avail, key=lambda k: (key[k], arr[k]))
        t += AIRTIME
        relay[j] = t
        done[j] = True
    return relay


def main():
    plot = "--plot" in sys.argv
    rng = np.random.default_rng(42)
    ml = cv_predict(word_pipe)
    rule = rule_predict()
    hyb = hybrid(rule, ml)
    conf = {"rule": confusion_rows(rule), "hybrid": confusion_rows(hyb)}

    for n in (20, 50):
        for arrival, label in (("sim", "all at once"), ("spread", "over ten minutes")):
            res = simulate(n, arrival, conf, rng)
            print(f"\n{n} reports, {label} "
                  f"(aggregate airtime {n*AIRTIME:.0f} s = {n*AIRTIME/60:.1f} min)")
            print(f"  {'discipline':8s} {'median (s)':>11s} {'p90 (s)':>9s}")
            for d in ("fcfs", "rule", "hybrid", "oracle"):
                v = res[d]
                print(f"  {d:8s} {np.median(v):11.1f} {np.percentile(v,90):9.1f}")
            if plot and n == 50 and arrival == "sim":
                _plot(res)


def _plot(res, path="figure6_queue.png"):
    """Figure 6 of the paper: CDF of the delay to LoRa relay of CRITICAL
    reports, 50 simultaneous reports, 5.6 s airtime, back-to-back."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    styles = {
        "fcfs":   dict(label="FIFO (released hub code)", color="#404040", ls="-",  lw=2.0),
        "rule":   dict(label="Priority: rule tier",      color="#E69F00", ls="--", lw=2.0),
        "hybrid": dict(label="Priority: hybrid",         color="#1F77B4", ls="-",  lw=2.0),
        "oracle": dict(label="Oracle (true class)",      color="#2CA02C", ls=":",  lw=2.2),
    }
    for d in ("fcfs", "rule", "hybrid", "oracle"):
        v = np.sort(res[d])
        cdf = np.arange(1, len(v) + 1) / len(v)
        ax.plot(np.r_[v[0], v], np.r_[0.0, cdf], **styles[d])
    ax.set_xlim(left=0)
    ax.set_xlabel("Delay from submission to LoRa relay of CRITICAL reports (s)")
    ax.set_ylabel("Cumulative fraction")
    ax.set_title("50 simultaneous reports, 5.6 s airtime, back-to-back", fontsize=9)
    ax.legend(loc="lower right", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=200)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
