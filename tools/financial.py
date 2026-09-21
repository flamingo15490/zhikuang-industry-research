"""工具10：财务指标扩展（新浪源）。成长/盈利/偿债/现金流。"""
from __future__ import annotations

import pandas as pd

from tools._resolve import resolve_stock, to_digits

FINANCIAL_INDICATORS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_financial_indicators",
        "description": (
            "查询个股财务指标：营收/净利增速、毛利率、净利率、ROE、资产负债率、流动比率、"
            "每股经营现金流。新浪财务指标源。输入股票代码或名称。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "股票代码或名称，如 601899 / 紫金矿业"}
            },
            "required": ["query"],
        },
    },
}


def get_financial_indicators(query: str) -> str:
    name, code = resolve_stock(query)
    if not name:
        return f"未找到与 '{query}' 匹配的股票"
    try:
        import akshare as ak  # 延迟导入，避免拖慢启动
        df = ak.stock_financial_analysis_indicator(symbol=to_digits(code), start_year="2023")
        if df.empty:
            return f"{name}：未获取到财务指标。"
        if "日期" in df.columns:
            df = df.sort_values("日期")
        # 口径统一：取最新年度(12-31)行，与画像/基本面一致，不混用半年度
        d = pd.to_datetime(df["日期"], errors="coerce")
        annual = df[d.dt.month == 12]
        row = annual.iloc[-1] if not annual.empty else df.iloc[-1]
        date = str(row.get("日期", ""))[:10]

        def pick(cands: list[str]) -> str:
            for c in cands:
                if c in df.columns and pd.notna(row.get(c)):
                    try:
                        return f"{float(row[c]):.2f}"
                    except (TypeError, ValueError):
                        return str(row[c])
            return "NA"

        lines = [
            f"{name}（{code}）财务指标（报告期 {date}，新浪源）：",
            f"- 成长性：营收增速 {pick(['主营业务收入增长率(%)'])}%，净利增速 {pick(['净利润增长率(%)'])}%",
            f"- 盈利：毛利率 {pick(['销售毛利率(%)'])}%，净利率 {pick(['销售净利率(%)'])}%，"
            f"ROE {pick(['加权净资产收益率(%)', '净资产收益率(%)'])}%",
            f"- 偿债：资产负债率 {pick(['资产负债率(%)'])}%，流动比率 {pick(['流动比率'])}，速动比率 {pick(['速动比率'])}",
            f"- 现金流：每股经营现金流 {pick(['每股经营性现金流(元)'])} 元",
        ]
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"财务指标获取失败：{type(exc).__name__}: {exc}"
