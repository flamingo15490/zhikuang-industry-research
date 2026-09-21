"""工具1：宏观状态查询。读取预计算的宏观状态指数（相对自身历史的滚动 z-score）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "data" / "macro" / "macro_regime_daily.parquet"

MACRO_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "query_macro_state",
        "description": (
            "查询有色金属相关宏观状态：工业金属状态、贵金属状态、战略金属状态。"
            "状态为滚动 z-score：正值=相对自身历史更强，负值=更弱；NA=覆盖不足。"
            "仅用于描述周期背景，经检验对收益预测无增量，不作为买卖/择时信号。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "可选，YYYY-MM-DD；不填返回最新交易日"}
            },
            "required": [],
        },
    },
}

_STATE_COLS = ["industrial_metals_state", "precious_metals_state", "strategic_metals_state"]


def _fmt(value) -> str:
    try:
        if pd.isna(value):
            return "NA"
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return "NA"


def query_macro_state(date: str | None = None) -> str:
    if not DATA_FILE.exists():
        return f"错误：宏观状态数据缺失，请把 macro_regime_daily.parquet 放到 {DATA_FILE}"
    df = pd.read_parquet(DATA_FILE).sort_values("date")
    if date:
        df = df[df["date"] <= pd.Timestamp(date)]
        if df.empty:
            return f"错误：{date} 之前没有宏观状态数据"
    row = df.iloc[-1]
    lines = [f"宏观状态（数据日期 {pd.Timestamp(row['date']).date()}）："]
    for col in _STATE_COLS:
        if col in row.index:
            lines.append(f"- {col} = {_fmt(row[col])}")
    if "industrial_coverage" in row.index and "precious_coverage" in row.index:
        lines.append(
            f"- 覆盖率：industrial={_fmt(row['industrial_coverage'])}，precious={_fmt(row['precious_coverage'])}"
        )
    lines.append("解释：z-score 为正=相对自身历史更强，为负=更弱；NA=覆盖不足未生成。仅作周期背景描述，经检验对收益预测无增量，不作买卖/择时信号。")
    return "\n".join(lines)
