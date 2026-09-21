"""统一图表视觉样式：专业金融配色 + 干净布局。

受 SciencePlots（GitHub: garrettj403/SciencePlots）的学术简洁风启发，
但不依赖其风格文件（与 matplotlib 3.11 不兼容），改为自研实现，保证可复现。
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 现代金融配色
C = {
    "blue": "#2563eb",      # 主蓝
    "cyan": "#0891b2",      # 青
    "indigo": "#4f46e5",    # 靛蓝
    "red": "#e11d48",       # 玫红（跌 / 负）
    "green": "#059669",     # 翠绿（涨 / 正）
    "amber": "#d97706",     # 琥珀
    "purple": "#7c3aed",    # 紫
    "slate": "#64748b",     # 石板灰
    "dark": "#0f172a",      # 近黑
    "grid": "#e2e8f0",      # 网格浅灰
    "edge": "#cbd5e1",      # 边框灰
}

# 饼图 / 多分类顺序色板（低饱和、协调）
PALETTE = ["#2563eb", "#0891b2", "#d97706", "#7c3aed", "#059669",
           "#e11d48", "#64748b", "#0ea5e9", "#f59e0b", "#10b981"]


def setup() -> None:
    """应用全局样式（幂等，可重复调用）。"""
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.edgecolor": C["edge"],
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.color": C["grid"],
        "grid.linewidth": 0.7,
        "grid.alpha": 0.9,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlecolor": C["dark"],
        "axes.labelcolor": C["slate"],
        "axes.labelsize": 9,
        "xtick.color": C["slate"],
        "ytick.color": C["slate"],
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
    })


setup()
