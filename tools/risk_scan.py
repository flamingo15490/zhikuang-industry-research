"""工具11：简化风险扫描（资产负债/盈利/偿债/少数股东/披露质量）。"""
from __future__ import annotations

import pandas as pd

from tools._resolve import PROFILE, resolve_stock, to_digits

RISK_SCAN_TOOL = {
    "type": "function",
    "function": {
        "name": "scan_risk",
        "description": (
            "简化风险扫描：检查高负债、净利负增长、流动比率过低、少数股东占比过高、"
            "主营披露不透明等预警项。仅覆盖可获取指标，非完整风控，结果需如实标注。输入股票代码或名称。"
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


def scan_risk(query: str) -> str:
    name, code = resolve_stock(query)
    if not name:
        return f"未找到与 '{query}' 匹配的股票"
    risks: list[str] = []

    # 1) 公司画像：少数股东占比 + 披露质量
    try:
        df = pd.read_parquet(PROFILE)
        r = df[df["code"] == code]
        if not r.empty:
            r = r.iloc[0]
            ms = r.get("minority_share")
            mq = r.get("metal_quality")
            if pd.notna(ms) and float(ms) > 0.30:
                risks.append(f"少数股东占比 {float(ms)*100:.0f}%（>30%），归母利润摊薄较明显")
            if mq in ("coarse", "merged"):
                risks.append(f"主营构成披露为 {mq}，金属业务透明度有限")
    except Exception:  # noqa: BLE001
        pass

    # 2) 财务指标：杠杆 / 盈利 / 偿债
    try:
        import akshare as ak
        fd = ak.stock_financial_analysis_indicator(symbol=to_digits(code), start_year="2023")
        if not fd.empty:
            if "日期" in fd.columns:
                fd = fd.sort_values("日期")
            row = fd.iloc[-1]

            def g(cands):
                for c in cands:
                    if c in fd.columns and pd.notna(row.get(c)):
                        try:
                            return float(row[c])
                        except (TypeError, ValueError):
                            return None
                return None

            debt = g(["资产负债率(%)"])
            growth = g(["净利润增长率(%)"])
            cur = g(["流动比率"])
            if debt is not None and debt > 70:
                risks.append(f"资产负债率 {debt:.1f}%（>70%），杠杆偏高")
            if growth is not None and growth < 0:
                risks.append(f"净利润增速 {growth:.1f}%（负增长）")
            if cur is not None and cur < 1:
                risks.append(f"流动比率 {cur:.2f}（<1），短期偿债压力")
    except Exception:  # noqa: BLE001
        pass

    if not risks:
        return (f"{name}：简化风险扫描未发现明显预警项"
                f"（覆盖：资产负债率/净利增速/流动比率/少数股东占比/披露质量，非完整风控）。")
    return f"{name} 简化风险扫描（⚠️ 非完整风控，仅覆盖可获取指标）：\n" + "\n".join(f"- {x}" for x in risks)
