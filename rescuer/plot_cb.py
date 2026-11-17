import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
d=pd.read_csv("crisisbench_metrics.csv"); a=d[d.section=="A. all events"].set_index("config")
ramp=["#ffffff","#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95","#0d366b"]
cmap=LinearSegmentedColormap.from_list("b",ramp); INK,MUTED="#1f1f1f","#5c5c5c"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9})
cfg=[("frozen-rule","(a) Rule tier"),("frozen-ml","(b) Learned model"),("frozen-hybrid","(c) Hybrid"),("retrained-ml","(d) Retrained on CrisisBench")]
fig,axes=plt.subplots(1,4,figsize=(12,3.3),constrained_layout=True)
for ax,(k,t) in zip(axes,cfg):
    r=a.loc[k]; cm=np.array([[r.TP,r.FN],[r.FP,r.TN]],float); pct=cm/cm.sum(1,keepdims=True)
    im=ax.imshow(pct,cmap=cmap,vmin=0,vmax=1)
    for i in range(2):
        for j in range(2):
            ax.text(j,i,f"{int(cm[i,j]):,}\n({pct[i,j]*100:.1f}%)",ha="center",va="center",fontsize=9,
                    fontweight="bold" if i==j else "normal",color="white" if pct[i,j]>=0.5 else INK)
    ax.set_xticks([0,1]); ax.set_yticks([0,1])
    ax.set_xticklabels(["Escalated","Not escalated"],color=MUTED,fontsize=8)
    ax.set_yticklabels(["Urgent","Other"],color=MUTED,fontsize=8)
    ax.set_xticks([-.5,.5,1.5],minor=True); ax.set_yticks([-.5,.5,1.5],minor=True)
    ax.grid(which="minor",color="white",linewidth=2); ax.tick_params(which="both",length=0)
    for s in ax.spines.values(): s.set_visible(False)
    ax.set_title(f"{t}\nprecision {r.precision:.2f} · recall {r.recall:.2f}",fontsize=9.5,color=INK)
    ax.set_xlabel("Decision",color=MUTED)
axes[0].set_ylabel("Label (urgent n = 2,036; other n = 13,533)",color=MUTED,fontsize=8)
cb=fig.colorbar(im,ax=axes,shrink=0.8,pad=0.01,format=lambda x,_:f"{x*100:.0f}%")
cb.set_label("Share of the labeled row",color=MUTED); cb.outline.set_visible(False); cb.ax.tick_params(colors=MUTED,length=0)
fig.savefig("crisisbench_confusion.png",dpi=300,facecolor="white")
