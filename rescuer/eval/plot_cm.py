import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

R = json.load(open("results.json"))
L = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ramp = ["#ffffff", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
cmap = LinearSegmentedColormap.from_list("seq_blue", ramp)
INK, MUTED = "#1f1f1f", "#5c5c5c"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), constrained_layout=True)
titles = [("rule", "(a) Rule tier"), ("learned", "(b) Learned model"), ("hybrid", "(c) Hybrid")]
for ax, (key, title) in zip(axes, titles):
    cm = np.array(R[key]["confusion"])
    im = ax.imshow(cm, cmap=cmap, vmin=0, vmax=50)
    for i in range(4):
        for j in range(4):
            v = cm[i, j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=10,
                    fontweight="bold" if i == j else "normal",
                    color="white" if v >= 25 else INK)
    ax.set_xticks(range(4)); ax.set_yticks(range(4))
    ax.set_xticklabels(L, fontsize=8, color=MUTED)
    ax.set_yticklabels(L, fontsize=8, color=MUTED)
    ax.set_xticks(np.arange(-.5, 4, 1), minor=True); ax.set_yticks(np.arange(-.5, 4, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("Predicted class", color=MUTED)
    rc = R[key]["per_class"]["CRITICAL"]["recall"]
    ax.set_title(f"{title}\nCRITICAL recall {rc:.2f}", fontsize=10, color=INK)
axes[0].set_ylabel("True class", color=MUTED)
cb = fig.colorbar(im, ax=axes, shrink=0.8, pad=0.02)
cb.set_label("Messages (n = 50 per true class)", color=MUTED)
cb.outline.set_visible(False)
cb.ax.tick_params(colors=MUTED, length=0)
fig.savefig("confusion_matrices.png", dpi=300, facecolor="white")
print("ok")
