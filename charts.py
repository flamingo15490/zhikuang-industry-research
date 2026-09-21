"""研报可视化（Plotly 交互版）：宏观周期时序、主营构成环形、电解铝成本瀑布。

交互特性：鼠标悬浮高亮 + 精确数值提示，支持缩放/平移/图例点选。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from tools.sector_matrix import METAL_CN

BASE = Path(__file__).resolve().parent
PROFILE = BASE / "data" / "company_profile_summary.parquet"
MACRO = BASE / "data" / "macro" / "macro_regime_daily.parquet"
METAL = BASE / "data" / "metal_prices.parquet"

# 配色（与 chart_style 对齐）
C = {
    "blue": "#2563eb", "red": "#e11d48", "green": "#059669", "amber": "#d97706",
    "purple": "#7c3aed", "slate": "#64748b", "dark": "#0f172a",
    "grid": "#e2e8f0", "edge": "#cbd5e1",
}
PALETTE = ["#2563eb", "#0891b2", "#d97706", "#059669", "#7c3aed",
           "#e11d48", "#f59e0b", "#10b981", "#6366f1", "#0ea5e9",
           "#db2777", "#84cc16", "#f97316", "#14b8a6"]

_FONT = dict(family="Microsoft YaHei, SimHei, sans-serif", color=C["dark"], size=12)
_BASE_LAYOUT = dict(
    template="plotly_white",
    font=_FONT,
    margin=dict(l=10, r=10, t=48, b=10),
    paper_bgcolor="white",
    plot_bgcolor="white",
    hoverlabel=dict(bgcolor="white", bordercolor=C["edge"],
                    font=dict(family="Microsoft YaHei, SimHei", color=C["dark"], size=12)),
)


def draw_macro_cycle(frame=None):
    """宏观周期：工业/贵金属/战略金属 滚动 z-score 时序（交互线图）。"""
    if frame is None:
        if not MACRO.exists():
            return None
        frame = pd.read_parquet(MACRO)
    if frame.empty:
        return None
    df = frame.copy().sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    series = [("industrial_metals_state", "工业金属", C["blue"]),
              ("precious_metals_state", "贵金属", C["amber"]),
              ("strategic_metals_state", "战略金属", C["purple"])]

    fig = go.Figure()
    for c, label, color in series:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df[c], mode="lines", name=label,
            line=dict(color=color, width=1.4),
            hovertemplate=f"{label} z-score %{{y:.2f}}<br>%{{x|%Y-%m-%d}}<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dash", line_color=C["edge"], line_width=0.8)
    fig.update_layout(
        **_BASE_LAYOUT,
        title=dict(text="宏观周期状态（滚动 z-score，仅背景描述，不作信号）", font=dict(size=13)),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=11)),
        yaxis=dict(title="z-score", gridcolor=C["grid"]),
        xaxis=dict(gridcolor=C["grid"]),
    )
    return fig


def draw_metal_mix(code: str):
    """主营构成：金属收入占比环形图（交互，悬浮显示占比）。披露不全返回 None。"""
    df = pd.read_parquet(PROFILE)
    r = df[df["code"] == code]
    if r.empty:
        return None
    r = r.iloc[0]
    if r.get("metal_quality") == "coarse":
        return None
    share_cols = [c for c in df.columns if c.endswith("_share") and c != "minority_share"]
    pairs = [(METAL_CN.get(c[:-6], c[:-6]), c[:-6], float(r[c]))
             for c in share_cols if pd.notna(r[c]) and float(r[c]) > 0]
    if not pairs:
        return None
    pairs.sort(key=lambda x: -x[2])
    labels = [p[0] for p in pairs]
    vals = [p[2] for p in pairs]
    keys = [p[1] for p in pairs]
    if sum(vals) < 0.999:
        labels.append("其他")
        vals.append(round(1 - sum(vals), 4))
        keys.append(None)

    fig = go.Figure(go.Pie(
        labels=labels, values=vals, hole=0.5, sort=False,
        ids=keys,
        customdata=keys,
        marker=dict(colors=PALETTE[:len(vals)], line=dict(color="white", width=2)),
        textinfo="label+percent", textposition="inside",
        insidetextfont=dict(color="white", size=12),
        hovertemplate="%{label}<br>占比 %{value:.1%}<extra></extra>",
    ))
    note = "（合并披露，均分近似，存在误差）" if r.get("metal_quality") == "merged" else ""
    fig.update_layout(
        **_BASE_LAYOUT,
        title=dict(text=f"{r['stock_name']} 主营构成{note}", font=dict(size=13)),
        legend=dict(x=1.02, y=0.5, font=dict(size=11)),
    )
    return fig


def draw_report_mix(analysis):
    """Same-period disclosed segment revenue; no legacy profile-share lookup."""
    import math
    from tools.sensitivity_core import segment_metals
    rows = analysis.get('segments', [])
    total = analysis.get('statement', {}).get('OPERATE_INCOME')
    if (not rows or analysis.get('period') != analysis.get('segment_period')
            or not isinstance(total, (int, float)) or not math.isfinite(total) or total <= 0):
        return None
    if (len({row['name'] for row in rows}) != len(rows) or any(row.get('excluded') or row.get('is_elimination')
            or not isinstance(row.get('revenue'), (int, float)) or not math.isfinite(row['revenue'])
            or row['revenue'] < 0 for row in rows)
            or abs(sum(row['revenue'] for row in rows) - total) > max(1, total * 1e-4)):
        return None
    keys = [segment_metals(row['name']) for row in rows]
    keys = [metals[0] if len(metals) == 1 else None for metals in keys]
    fig = go.Figure(go.Pie(labels=[row['name'] for row in rows],
        values=[row['revenue'] / total for row in rows], hole=.5, sort=False,
        customdata=keys, ids=keys, textinfo='percent', textposition='inside',
        marker=dict(colors=PALETTE, line=dict(color='white', width=1)),
        hovertemplate='%{label}<br>收入占比 %{value:.1%}<extra></extra>'))
    fig.update_layout(**_BASE_LAYOUT,
        title=dict(text=f"{analysis['name']} 分部收入构成（{analysis['period']}）", font=dict(size=13)),
        legend=dict(orientation='h', y=-.05, font=dict(size=11)))
    return fig


def draw_cost_waterfall(electricity_price: float = 0.45):
    """电解铝成本拆分瀑布图：铝价 → 减氧化铝/电力/辅料 → 吨铝利润（交互）。"""
    if not METAL.exists():
        return None
    mp = pd.read_parquet(METAL)
    mp["date"] = pd.to_datetime(mp["date"])
    sub = mp[mp["aluminum"].notna() & mp["alumina"].notna()]
    if sub.empty:
        return None
    last = sub.iloc[-1]
    al, ao = float(last["aluminum"]), float(last["alumina"])
    oxi = 1.93 * ao
    power = 13500 * electricity_price
    other = 2500.0
    profit = al - oxi - power - other

    x = ["沪铝价", f"−氧化铝<br>1.93×{ao:.0f}",
         f"−电力<br>13500×{electricity_price:.2f}", "−阳极辅料", "= 吨铝利润"]
    y = [al, -oxi, -power, -other, profit]
    measure = ["absolute", "relative", "relative", "relative", "total"]

    fig = go.Figure(go.Waterfall(
        x=x, y=y, measure=measure,
        text=[f"{v:+,.0f}" for v in y], textposition="outside",
        connector=dict(line=dict(color=C["slate"], width=1, dash="dot")),
        increasing=dict(marker=dict(color=C["blue"])),
        decreasing=dict(marker=dict(color=C["red"])),
        totals=dict(marker=dict(color=C["green"])),
        hovertemplate="%{x}<br>%{y:+,.0f} 元/吨<extra></extra>",
    ))
    fig.update_layout(
        **_BASE_LAYOUT,
        title=dict(text=f"电解铝吨铝利润拆分（截至 {last['date'].date()}）", font=dict(size=13)),
        yaxis=dict(title="元/吨", gridcolor=C["grid"]),
        xaxis=dict(gridcolor=C["grid"]),
        showlegend=False,
    )
    return fig
