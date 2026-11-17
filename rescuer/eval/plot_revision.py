"""Figure 10 (link measurements, Tables 10-11) and Figure 7 (classifier performance vs cost, Table 9) of the paper."""
import json, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, MUTED, GRID = "#1f1f1f", "#5c5c5c", "#e6e6e3"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"   # validated categorical slots 1-3
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED})

# ---------- data (all measured; see Tables 10 and 11) ----------
elev = [(478, -95, 5), (853, -105, -5), (2807, -86, 11), (5198, -110, -1)]   # elevated site
ground = [(18, -43, 9), (45, -60, 9), (294, -86, 6), (2950, -85, 7), (3110, -95, -5),
          (3180, -92, 1), (3300, -96, -5), (3450, -96, -9)]                   # hub in vehicle
rep = dict(d=5, mean=-53.3, sd=4.6, lo=-67, hi=-42, n=30)                     # 30 repeated reports

band = [g for g in ground if g[0] >= 2950]
r = np.array([b[1] for b in band]); s = np.array([b[2] for b in band])
stats = dict(n=len(band), rssi_mean=r.mean(), rssi_sd=r.std(ddof=1), snr_mean=s.mean(), snr_sd=s.std(ddof=1),
             snr_min=s.min(), margin_db=s.min() - (-12.5))
def wilson_low(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
stats.update(ci_band=wilson_low(5, 5), ci_ground=wilson_low(8, 8), ci_rep=wilson_low(30, 30),
             ci_all_new=wilson_low(38, 38))
json.dump(stats, open("link_stats.json", "w"), indent=1, default=float)
print(stats)

fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.9), constrained_layout=True)
for ax in (a1, a2):
    ax.set_xscale("log"); ax.set_xlim(3, 9000)
    ax.grid(True, which="major", color=GRID, linewidth=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    ax.set_xlabel("Hub–station distance from GPS (m, log scale)")
    ax.set_xticks([5, 10, 50, 100, 500, 1000, 5000]); ax.set_xticklabels(["5", "10", "50", "100", "500", "1k", "5k"])

# (a) RSSI
a1.errorbar([rep["d"]], [rep["mean"]], yerr=[[rep["mean"] - rep["lo"]], [rep["hi"] - rep["mean"]]],
            fmt="none", ecolor=S3, elinewidth=1.2, capsize=3)
a1.errorbar([rep["d"]], [rep["mean"]], yerr=[rep["sd"]], fmt="D", color=S3, ms=8, mec="white", mew=1.5,
            elinewidth=4, capsize=0, label="Repeated delivery, 30/30 (mean, ±SD, range)")
a1.plot([g[0] for g in ground], [g[1] for g in ground], "o", color=S2, ms=8, mec="white", mew=1.5,
        label="Ground level, hub in vehicle, 8/8")
a1.plot([e[0] for e in elev], [e[1] for e in elev], "s", color=S1, ms=8, mec="white", mew=1.5,
        label="Elevated site, open terrain, 4/4")
a1.axhline(-129, color=MUTED, ls=":", lw=1)
a1.text(3.3, -127, "module sensitivity stated in the datasheet (−129 dBm)", color=MUTED, fontsize=7.5)
a1.set_ylim(-135, -35); a1.set_ylabel("RSSI (dBm)")
a1.set_title("(a) Received signal strength", loc="left", color=INK, fontsize=10)
a1.legend(loc="upper right", frameon=False, fontsize=7.5)

# (b) SNR
a2.plot([g[0] for g in ground], [g[2] for g in ground], "o", color=S2, ms=8, mec="white", mew=1.5,
        label="Ground level, hub in vehicle")
a2.plot([e[0] for e in elev], [e[2] for e in elev], "s", color=S1, ms=8, mec="white", mew=1.5,
        label="Elevated site, open terrain")
a2.axhline(-12.5, color=MUTED, ls=":", lw=1)
a2.text(3.3, -14.6, "nominal SF9 demodulation limit (−12.5 dB)", color=MUTED, fontsize=7.5)
a2.annotate("", xy=(3450, -12.5), xytext=(3450, -9), arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9))
a2.text(2350, -10.8, "≈3.5 dB\nmargin", ha="right", va="center", fontsize=7.5, color=INK)
a2.set_ylim(-17, 15); a2.set_ylabel("SNR (dB)")
a2.set_title("(b) Signal-to-noise ratio", loc="left", color=INK, fontsize=10)
a2.legend(loc="upper right", frameon=False, fontsize=7.5)
fig.savefig("fig_link.png", dpi=300, facecolor="white")

# ---------- Figure 7: performance vs cost ----------
M = json.load(open("compare_models.json"))
short = {"Logistic regression (deployed)": "Logistic regression\n(deployed)", "Linear SVM": "Linear SVM",
         "Multinomial naive Bayes": "Naive Bayes", "k-nearest neighbours (k=5, cosine)": "k-NN",
         "Decision tree": "Decision tree", "Random forest (200 trees)": "Random forest"}
off = {"Logistic regression (deployed)": (-14, -24), "Linear SVM": (-12, 12), "Multinomial naive Bayes": (8, 4),
       "k-nearest neighbours (k=5, cosine)": (8, -3), "Decision tree": (8, -3), "Random forest (200 trees)": (-8, 8)}
fig, ax = plt.subplots(figsize=(6.4, 3.9), constrained_layout=True)
for k, lab in short.items():
    d = M[k]; x = d["predict_ms_median"]; mf, sd = d["seeds20"]["macro_f1"]
    dep = k.startswith("Logistic")
    ax.errorbar([x], [mf], yerr=[sd], fmt="o", color=S2 if dep else S1, ms=9 if dep else 7,
                mec="white", mew=1.5, elinewidth=1.2, capsize=3)
    dx, dy = off[k]
    ax.annotate(lab, (x, mf), xytext=(dx, dy), textcoords="offset points", fontsize=8, color=INK,
                ha="right" if dx < 0 else "left")
ax.set_xscale("log"); ax.set_xlim(0.1, 30)
ax.set_xticks([0.1, 0.3, 1, 3, 10, 30]); ax.set_xticklabels(["0.1", "0.3", "1", "3", "10", "30"])
ax.set_ylim(0.55, 0.9)
ax.set_xlabel("Prediction time per message (ms, median, log scale)")
ax.set_ylabel("Macro-F1 (mean ± SD, 20 fold assignments)")
ax.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
fig.savefig("fig_models.png", dpi=300, facecolor="white")
print("ok")
