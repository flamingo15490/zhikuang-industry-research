"""Small, dependency-free helpers shared by interactive UI callbacks."""
from __future__ import annotations

from collections.abc import Mapping
from html import escape


METAL_LABELS = {
    "黄金": "gold",
    "铜": "copper",
    "铝": "aluminum",
    "银": "silver",
    "锌": "zinc",
    "锡": "tin",
    "铅": "lead",
    "镍": "nickel",
    "锂": "lithium",
    "稀土": "rare_earth",
    "钼": "molybdenum",
    "钨": "tungsten",
    "锑": "antimony",
    "钴": "cobalt",
}


def metal_key_from_selection(selection) -> str | None:
    """Resolve a Plotly/Gradio selection to a canonical metal key."""
    if isinstance(selection, Mapping):
        customdata = selection.get("customdata")
        label = selection.get("label") or selection.get("value")
        if isinstance(customdata, (list, tuple)):
            customdata = customdata[0] if customdata else None
        if isinstance(customdata, str) and customdata in set(METAL_LABELS.values()):
            return customdata
        selection = label
    if not isinstance(selection, str):
        return None
    value = selection.strip()
    if value in METAL_LABELS:
        return METAL_LABELS[value]
    return value if value in set(METAL_LABELS.values()) else None


def comparison_trace_names(stock_name: str, peer_name: str) -> list[str]:
    """Return stable legend labels for an individual/peer comparison."""
    return [str(stock_name), f"{peer_name}均值"]


def format_radar_details(stock_name: str, peer_name: str, rank: int, size: int,
                         scores: Mapping[str, float]) -> str:
    """Format the complete ranking and dimension scores shown below the radar."""
    ordered = ["基本面", "估值", "技术面", "资金面", "安全度"]
    values = [float(scores.get(k, 0)) for k in ordered]
    composite = sum(values) / len(values) if values else 0
    score_text = " · ".join(f"{k} {v:.0f}" for k, v in zip(ordered, values))
    return (f"**{stock_name} · {peer_name}排名 {int(rank)} / {int(size)}**　"
            f"综合分 {composite:.0f}\n\n{score_text}")


def format_peer_ranking(peer_name: str, rows: list[tuple[str, float]], rank: int | None = None) -> str:
    """Return an HTML hover card containing the complete peer ranking."""
    rows = sorted(rows, key=lambda row: -float(row[1]))
    items = []
    previous = None
    position = 0
    for i, (name, score) in enumerate(rows, 1):
        if previous is None or float(score) != previous:
            position = i
        previous = float(score)
        items.append(f"<li><span>{position}. {escape(str(name))}</span><b>{float(score):.1f}</b></li>")
    peer_name = escape(str(peer_name))
    trigger = f"{peer_name}排名 {int(rank)} / {len(rows)}" if rank else f"{peer_name}排名"
    return (f'<div class="rank-hover-wrap"><span class="rank-trigger">{trigger}</span>'
            f'<div class="rank-tooltip"><strong>{peer_name}板块完整排名 · 综合分</strong>'
            f'<ol>{"".join(items)}</ol></div></div>')
