"""公司历史财报画像；未标期间的金属占比不作为同期金额依据。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools._resolve import resolve_profile_row

BASE = Path(__file__).resolve().parent.parent
PROFILE = BASE / "data" / "company_profile_summary.parquet"

COMPANY_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_company_profile",
        "description": (
            "查询公司历史财报画像：有效税率、少数股东占比与对应报表日期。"
            "画像金属占比期间未核验，默认不输出；同期间分部收入和毛利应查询get_profit_analysis。"
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


def _pct(v) -> str:
    return "NA" if pd.isna(v) else f"{float(v):.1%}"


def get_company_profile(query: str) -> str:
    if not PROFILE.exists():
        return "错误：公司画像数据缺失，请先运行 scripts/build_company_profile.py"
    df = pd.read_parquet(PROFILE)
    r = resolve_profile_row(df, query)
    if r is None:
        return f"未找到与 '{query}' 唯一匹配的股票，请提供完整名称或股票代码。"
    quality = r.get("metal_quality", "?")
    lines = [
        f"{r['stock_name']}（{r['code']}）经营画像"
        f"（报告期 {pd.Timestamp(r['report_date']).date()}，公告日 {pd.Timestamp(r['notice_date']).date()}）：",
        f"- 有效税率：{_pct(r['tax_rate'])}",
        f"- 少数股东占比：{_pct(r['minority_share'])}",
    ]

    lines.append(f'- 画像金属标签状态：{quality}；该状态不等于占比数值已通过同期间校验。')
    lines.append('- 金属收入占比期间未核验，默认省略；上述日期仅属于税率和少数股东比例的利润表。')
    lines.append('- 请调用 get_profit_analysis 查询同报告期分部收入与毛利；不要从画像归一化占比反推公司金额。')
    return "\n".join(lines)
