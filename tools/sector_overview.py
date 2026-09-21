"""工具3：板块覆盖与主营金属定位。exposure 仅用于业务定位，不作为收益信号。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
EXPOSURE_FILE = BASE / "data" / "nonferrous_subindustry_exposure.csv"
FUND_FILE = BASE / "data" / "nonferrous_fundamentals.parquet"

SECTOR_TOOL = {
    "type": "function",
    "function": {
        "name": "list_sector_stocks",
        "description": (
            "列出有色金属板块覆盖的股票及主营金属定位（工业金属/贵金属/战略金属）。"
            "可选子行业过滤，如 copper、gold。主营信息仅用于业务解释，不作为收益信号。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subindustry": {"type": "string", "description": "可选，如 copper、gold、rare_earth"}
            },
            "required": [],
        },
    },
}


def list_sector_stocks(subindustry: str | None = None) -> str:
    if not EXPOSURE_FILE.exists():
        return _fallback_from_fundamentals()
    exp = pd.read_csv(EXPOSURE_FILE)
    keep = [c for c in ["code", "stock_name", "subindustry", "subindustry_group"] if c in exp.columns]
    exp = exp[keep].drop_duplicates()

    available = sorted(exp["subindustry"].dropna().astype(str).unique())
    if subindustry:
        q = str(subindustry).strip().lower()
        hit = exp["subindustry"].astype(str).str.lower().str.contains(q, na=False)
        if "subindustry_group" in exp.columns:
            hit |= exp["subindustry_group"].astype(str).str.lower().str.contains(q, na=False)
        exp = exp[hit]
        if exp.empty:
            return f"未找到子行业 '{subindustry}'，可选：{available}"

    lines = [
        f"有色板块覆盖 {exp['code'].nunique()} 只股票"
        "（主营信息仅用于定位，经检验对收益无增量，不作为信号）："
    ]
    for (grp, si), group in exp.groupby(["subindustry_group", "subindustry"], dropna=False):
        uniq = group.drop_duplicates("code")
        items = "、".join(f"{n}（{c}）" for c, n in zip(uniq["code"], uniq["stock_name"]))
        lines.append(f"- {grp} / {si}：{items}")
    return "\n".join(lines)


def _fallback_from_fundamentals() -> str:
    if not FUND_FILE.exists():
        return "错误：缺少板块成分数据（exposure csv 或 fundamentals parquet 均缺失）。"
    df = pd.read_parquet(FUND_FILE)
    uniq = df[["code", "stock_name"]].drop_duplicates().sort_values("code")
    lines = ["有色板块覆盖（仅代码+名称，无子行业定位）："]
    lines += [f"- {r['stock_name']}（{r['code']}）" for _, r in uniq.iterrows()]
    return "\n".join(lines)
