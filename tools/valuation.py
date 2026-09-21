"""工具2：个股基本面快照。读取 nonferrous_fundamentals.parquet，给出最新报告期指标与板块分位。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "data" / "nonferrous_fundamentals.parquet"

VALUATION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock_fundamentals",
        "description": (
            "查询某只有色个股的最新基本面：ROE、毛利率、EPS、每股净资产、经营现金流，"
            "并给出相对板块中位的对比。输入股票代码或名称，如 '600111' 或 '北方稀土'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "股票代码或名称"}
            },
            "required": ["query"],
        },
    },
}

_METRICS = ["roe", "gross_margin", "eps", "bps", "ocfps"]


def _f(value, digits: int = 2) -> str:
    try:
        if pd.isna(value):
            return "NA"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "NA"


def get_stock_fundamentals(query: str) -> str:
    if not DATA_FILE.exists():
        return f"错误：基本面数据缺失，请把 nonferrous_fundamentals.parquet 放到 {DATA_FILE}"
    df = pd.read_parquet(DATA_FILE)
    q = str(query).strip().lower()

    def _hit(col: str) -> pd.Series:
        return df[col].astype(str).str.lower().str.contains(q, na=False)

    sub = df[_hit("code") | _hit("plain") | _hit("stock_name")]
    if sub.empty:
        return f"未找到与 '{query}' 匹配的有色个股，可用 list_sector_stocks 查看覆盖范围。"

    latest_all = df.sort_values(["code", "report_period", "ann_date"]).groupby("code").tail(1)
    median = {c: latest_all[c].median() for c in _METRICS}

    latest = sub.sort_values(["code", "report_period", "ann_date"]).groupby("code").tail(1)
    parts = []
    for _, r in latest.iterrows():
        period = pd.Timestamp(r["report_period"]).date()
        ann = pd.Timestamp(r["ann_date"]).date()
        parts.append(
            f"{r['stock_name']}（{r['code']}）\n"
            f"- 报告期 {period}（公告日 {ann}）\n"
            f"- ROE {_f(r['roe'])}%（板块中位 {_f(median['roe'])}%）\n"
            f"- 毛利率 {_f(r['gross_margin'])}%（中位 {_f(median['gross_margin'])}%）\n"
            f"- EPS {_f(r['eps'], 4)}（中位 {_f(median['eps'], 4)}）\n"
            f"- 每股净资产 {_f(r['bps'])}\n"
            f"- 经营现金流/股 {_f(r['ocfps'], 4)}"
        )
    return "\n\n".join(parts)
