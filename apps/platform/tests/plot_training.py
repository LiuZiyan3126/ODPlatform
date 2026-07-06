#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : plot_training.py
# @Author    : 雨霓同学  (refactor)
# @Function  : YOLO 训练过程可视化 —— 出版级多面板图表
#
# 设计说明
# --------
#   · 配色 : Okabe–Ito 色觉友好色板（对色盲 & 黑白打印均安全，学术可辩护）
#   · 排版 : 3×2 面板，去顶/右边框，浅网格，(a)–(f) 角标，衬线字体
#   · 数据 : time 为“累计”耗时 → 用差分还原“每轮”耗时；lr 三组完全重合 → 合并一条
#   · 公式 : 在总损失面板嵌入 YOLO 复合损失定义（LaTeX / mathtext 皆可）
#
# 两种渲染模式（切换 USE_LATEX 即可）
#   USE_LATEX = True   PGF + XeLaTeX + ctex，出矢量 PDF，投稿出版用（需本地 TeX 环境）
#   USE_LATEX = False  matplotlib 内置 mathtext + 系统中文衬线字体，免 LaTeX，可直接出图预览

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib import rcParams
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, ScalarFormatter

# ============================================================
# 0. 渲染模式
# ============================================================
USE_LATEX = True    # 出版模式(PGF+XeLaTeX+ctex,出矢量PDF)。想免LaTeX快速预览改为 False

CSV_PATH = "results.csv"
OUT_PDF  = "training_results.pdf"
OUT_PNG  = "training_results.png"   # 仅 USE_LATEX=False 时额外输出


def _first_available(cands):
    """返回候选列表中第一个系统已安装的字体名，找不到返回 None。"""
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in cands:
        if name in installed:
            return name
    return None


if USE_LATEX:
    matplotlib.use("pgf")
    rcParams.update({
        "font.family": "serif",
        "text.usetex": True,
        "pgf.rcfonts": False,
        "pgf.preamble": "\n".join([
            r"\usepackage{amsmath}",
            r"\usepackage{amssymb}",
            r"\usepackage{ctex}",
            r"\setmainfont{Times New Roman}",
            r"\setCJKmainfont{宋体}",
        ]),
    })
else:
    latin = _first_available(
        ["Times New Roman", "Nimbus Roman No9 L", "Nimbus Roman", "DejaVu Serif"])
    cjk = _first_available(
        ["SimSun", "宋体", "Songti SC", "STSong",
         "Source Han Serif SC", "Source Han Serif CN",
         "Noto Serif CJK SC", "Noto Serif CJK JP", "Noto Serif CJK",
         "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "Microsoft YaHei"])
    serif_stack = [f for f in (latin, cjk, "DejaVu Serif") if f]
    rcParams.update({
        "font.family": "serif",
        "font.serif": serif_stack,
        "mathtext.fontset": "stix",
        "axes.unicode_minus": False,
    })

# ------------------------------------------------------------
# 全局出版级样式
# ------------------------------------------------------------
rcParams.update({
    "font.size":          11,
    "axes.titlesize":     12,
    "axes.labelsize":     11,
    "xtick.labelsize":    9.5,
    "ytick.labelsize":    9.5,
    "legend.fontsize":    8.8,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.linewidth":     0.9,
    "axes.edgecolor":     "#3d3d3d",
    "axes.titlepad":      8,
    "axes.labelpad":      4,
    "xtick.direction":    "out",
    "ytick.direction":    "out",
    "xtick.major.size":   3.5,
    "ytick.major.size":   3.5,
    "xtick.major.width":  0.9,
    "ytick.major.width":  0.9,
    "xtick.color":        "#3d3d3d",
    "ytick.color":        "#3d3d3d",
    "lines.linewidth":    1.8,
    "lines.solid_capstyle": "round",
    "legend.frameon":     False,
    "figure.dpi":         120,
    "savefig.dpi":        300,
    "savefig.bbox":       "tight",
})

# Okabe–Ito 色板
C = {
    "box":     "#0072B2",  # blue
    "cls":     "#D55E00",  # vermillion
    "dfl":     "#009E73",  # bluish green
    "train":   "#0072B2",
    "val":     "#D55E00",
    "prec":    "#0072B2",
    "rec":     "#D55E00",
    "map50":   "#009E73",
    "map5095": "#CC79A7",  # reddish purple
    "lr":      "#0072B2",
    "time":    "#525252",
    "accent":  "#D55E00",
    "grid":    "#B7B7B7",
    "muted":   "#5a5a5a",
}

GRID_KW = dict(color=C["grid"], linewidth=0.6, alpha=0.55)


def style_axes(ax, letter, title=None):
    """统一网格 + 左上角面板编号 (a)、(b)…，可选居中标题。"""
    ax.grid(True, **GRID_KW)
    ax.set_axisbelow(True)
    ax.set_title(f"({letter})", loc="left", fontweight="bold", fontsize=12)
    if title:                                    # 想要纯期刊风(仅角标)：删掉此标题即可
        ax.set_title(title, loc="center")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))


# ============================================================
# 1. 读取数据
# ============================================================
df = pd.read_csv(CSV_PATH)
df.columns = df.columns.str.strip()        # 稳妥：清掉可能的前后空格

e = df["epoch"].to_numpy(dtype=float)

# 复合损失
train_total = (
    df["train/box_loss"].to_numpy(dtype=float)
    + df["train/cls_loss"].to_numpy(dtype=float)
    + df["train/dfl_loss"].to_numpy(dtype=float)
)
val_total = (
    df["val/box_loss"].to_numpy(dtype=float)
    + df["val/cls_loss"].to_numpy(dtype=float)
    + df["val/dfl_loss"].to_numpy(dtype=float)
)

# 每轮耗时（time 是累计值 → 差分；首轮直接取首值）
t = df["time"].to_numpy(dtype=float)
per_epoch = np.empty_like(t, dtype=float)
per_epoch[0] = t[0]
if len(t) > 1:
    per_epoch[1:] = np.diff(t)
else:
    per_epoch[1:] = np.array([], dtype=float)
steady = float(np.median(per_epoch[1:])) if len(per_epoch) > 1 else float(per_epoch[0])

e_min = float(np.min(e))
e_max = float(np.max(e))

# ============================================================
# 2. 画布
# ============================================================
fig, axes = plt.subplots(2, 3, figsize=(15.5, 9.2), constrained_layout=True)
fig.suptitle("目标检测模型训练过程可视化", fontsize=16, fontweight="bold")

# ---------- (a) 训练 / 验证损失 ----------
ax = axes[0, 0]
for key, tr, va in [("box", "train/box_loss", "val/box_loss"),
                    ("cls", "train/cls_loss", "val/cls_loss"),
                    ("dfl", "train/dfl_loss", "val/dfl_loss")]:
    ax.plot(e, df[tr], color=C[key], lw=1.8)                 # 实线 = train
    ax.plot(e, df[va], color=C[key], lw=1.5, ls=(0, (5, 2)))  # 虚线 = val
ax.set_xlabel("Epoch"); ax.set_ylabel("Loss")
ax.set_xlim(e_min, e_max)
# 双图例：颜色区分损失项，线型区分 train/val
comp_handles = [Line2D([0], [0], color=C[k], lw=1.8, label=lab)
                for k, lab in [("box", "Box"), ("cls", "Cls"), ("dfl", "DFL")]]
style_handles = [Line2D([0], [0], color=C["muted"], lw=1.8, ls="-",          label="Train"),
                 Line2D([0], [0], color=C["muted"], lw=1.5, ls=(0, (5, 2)), label="Val")]
leg1 = ax.legend(handles=comp_handles, loc="upper right",
                 title="Loss term", handlelength=1.6, borderaxespad=0.4)
leg1._legend_box.align = "left"
ax.add_artist(leg1)
ax.legend(handles=style_handles, loc="upper right",
          bbox_to_anchor=(1.0, 0.72), handlelength=1.8, borderaxespad=0.4)
style_axes(ax, "a", "训练与验证损失")

# ---------- (b) 总损失 + 复合损失公式 ----------
ax = axes[0, 1]
ax.plot(e, train_total, color=C["train"], lw=1.9, label="Train")
ax.plot(e, val_total,   color=C["val"],   lw=1.7, ls=(0, (5, 2)), label="Val")
i_min = int(np.argmin(val_total))
ax.scatter(e[i_min], val_total[i_min], s=34, color=C["val"],
           zorder=5, edgecolor="white", linewidth=0.8)
ax.annotate(f"val min {val_total[i_min]:.2f} (epoch {int(e[i_min])})",
            xy=(e[i_min], val_total[i_min]),
            xytext=(e[i_min] - 150, val_total[i_min] + 1.1),
            fontsize=8.5, color=C["muted"],
            arrowprops=dict(arrowstyle="-", color=C["muted"], lw=0.8))
ax.set_xlabel("Epoch"); ax.set_ylabel("Total loss")
ax.set_xlim(e_min, e_max)
ax.text(0.97, 0.93,
        r"$\mathcal{L}=\lambda_{\mathrm{box}}\mathcal{L}_{\mathrm{box}}"
        r"+\lambda_{\mathrm{cls}}\mathcal{L}_{\mathrm{cls}}"
        r"+\lambda_{\mathrm{dfl}}\mathcal{L}_{\mathrm{dfl}}$",
        transform=ax.transAxes, ha="right", va="top", fontsize=11,
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=C["grid"], lw=0.7))
ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.70))
style_axes(ax, "b", "总损失")

# ---------- (c) 精确率 / 召回率 ----------
ax = axes[0, 2]
ax.plot(e, df["metrics/precision(B)"], color=C["prec"], label="Precision")
ax.plot(e, df["metrics/recall(B)"],    color=C["rec"],  label="Recall")
ax.set_xlabel("Epoch"); ax.set_ylabel("Score")
ax.set_xlim(e_min, e_max); ax.set_ylim(0, 1.02)
ax.legend(loc="lower right")
style_axes(ax, "c", "精确率与召回率")

# ---------- (d) mAP，标注峰值 ----------
ax = axes[1, 0]
for col, ckey, lab in [("metrics/mAP50(B)",    "map50",   r"mAP@0.5"),
                       ("metrics/mAP50-95(B)", "map5095", r"mAP@0.5:0.95")]:
    y = df[col].to_numpy(dtype=float)
    ax.plot(e, y, color=C[ckey], label=lab)
    j = int(np.argmax(y))
    ax.scatter(e[j], y[j], s=30, color=C[ckey], zorder=5,
               edgecolor="white", linewidth=0.8)
    ax.annotate(f"{y[j]:.3f}", xy=(e[j], y[j]), xytext=(0, 7),
                textcoords="offset points", ha="center",
                fontsize=8.5, color=C[ckey])
ax.set_xlabel("Epoch"); ax.set_ylabel("mAP")
ax.set_xlim(e_min, e_max); ax.set_ylim(0, 1.05)
ax.legend(loc="lower right")
style_axes(ax, "d", "mAP")

# ---------- (e) 学习率（三组重合，合并一条） ----------
ax = axes[1, 1]
ax.plot(e, df["lr/pg0"], color=C["lr"], label="pg0 = pg1 = pg2")
lr_pg0 = df["lr/pg0"].to_numpy(dtype=float)
k_peak = int(np.argmax(lr_pg0))
ax.annotate("warm-up peak", xy=(e[k_peak], lr_pg0[k_peak]),
            xytext=(e[k_peak] + 40, lr_pg0[k_peak]),
            fontsize=8.5, color=C["muted"], va="center",
            arrowprops=dict(arrowstyle="->", color=C["muted"], lw=0.8))
ax.set_xlabel("Epoch"); ax.set_ylabel("Learning rate")
ax.set_xlim(e_min, e_max)
sf = ScalarFormatter(useMathText=True); sf.set_powerlimits((-2, 2))
ax.yaxis.set_major_formatter(sf)
ax.legend(loc="upper right")
style_axes(ax, "e", "学习率调度")

# ---------- (f) 每轮训练耗时 ----------
ax = axes[1, 2]
ax.plot(e, per_epoch, color=C["time"], lw=1.1,
        marker="o", ms=2.4, mfc=C["time"], mec="none", alpha=0.9)
ax.axhline(steady, ls="--", lw=1.1, color=C["accent"],
           label=f"steady median $\\approx$ {steady:.2f} s")
ax.set_xlabel("Epoch"); ax.set_ylabel("Time per epoch (s)")
ax.set_xlim(e_min, e_max)
ax.legend(loc="upper right")
style_axes(ax, "f", "每轮训练耗时")

# ============================================================
# 3. 输出
# ============================================================
fig.savefig(OUT_PDF)
if not USE_LATEX:
    fig.savefig(OUT_PNG)
print("saved:", OUT_PDF, "| steady/epoch =", round(steady, 3), "s | epochs =", len(e))
