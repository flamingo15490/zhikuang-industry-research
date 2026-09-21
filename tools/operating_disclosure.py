"""Pair exact, sourced product prices and composite unit costs without allocation."""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path

METRICS_PATH = Path(__file__).resolve().parents[1] / "data" / "profit_analysis" / "operating_metrics.json"
PRICE = "销售单价（不含税）"
COST = "单位销售成本"


def disclosure_for_analysis(analysis):
    """Use a report's captured disclosure instead of reading a newer local file."""
    from copy import deepcopy
    if '_operating_snapshot' not in analysis:
        return load_operating_disclosure(analysis.get('code'), analysis.get('period'))
    captured = analysis['_operating_snapshot']
    if (isinstance(captured, dict) and captured.get('code') == analysis.get('code')
            and captured.get('period') == analysis.get('period') and isinstance(captured.get('data'), dict)):
        return deepcopy(captured['data'])
    return dict(records=[], products=[], period=analysis.get('period'), warnings=['研究经营披露对象或期间不一致，未改用其他数据。'])


def load_operating_disclosure(code: str, period: str | None) -> dict:
    result = {"records": [], "products": [], "period": period, "warnings": []}
    warnings = result["warnings"]
    if not code or not period:
        warnings.append("未指定公司及报告期，未选择经营披露数据。")
        return result
    try:
        rows = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("经营披露数据必须为记录列表")
    except (OSError, ValueError) as exc:
        warnings.append(f"经营披露数据不可用：{type(exc).__name__}")
        return result
    records = [row for row in rows if isinstance(row, dict)
               and row.get("code") == code and row.get("period") == period]
    # Only identical full records are redundant; different provenance stays ambiguous.
    seen = set()
    for row in records:
        identity = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if identity not in seen:
            result["records"].append(row)
            seen.add(identity)
    if not result["records"]:
        warnings.append("该公司该报告期暂无经营披露记录。")
        return result

    groups = defaultdict(lambda: {PRICE: [], COST: []})
    for row in result["records"]:
        metric = row.get("metric")
        if metric not in (PRICE, COST):
            continue
        name, unit, scope = (row.get(key) for key in ("commodity", "unit", "scope"))
        if not all(isinstance(value, str) and value.strip() for value in (name, unit, scope)):
            warnings.append("经营价格或成本缺少产品、单位或业务范围，未计算单位毛利。")
            continue
        groups[(name, unit, scope)][metric].append(row)

    for (name, unit, scope), group in groups.items():
        if len(group[PRICE]) != 1 or len(group[COST]) != 1:
            warnings.append(f"{name}：同单位、同范围的售价或成本缺失/存在多条记录，未计算单位毛利。")
            continue
        price_row, cost_row = group[PRICE][0], group[COST][0]
        if any(row.get("verification") != "announcement_text_checked" for row in (price_row, cost_row)):
            warnings.append(f"{name}：售价或成本未完成公告文本核对。")
            continue
        source = price_row.get("source_url")
        if not isinstance(source, str) or not source.startswith(("https://", "http://")) or source != cost_row.get("source_url"):
            warnings.append(f"{name}：售价与成本来源不一致或缺失，未配对。")
            continue
        price, cost = price_row.get("value"), cost_row.get("value")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in (price, cost)):
            warnings.append(f"{name}：售价或单位成本不是有效非负数值。")
            continue
        margin = price - cost
        if not math.isfinite(margin):
            warnings.append(f"{name}：单位毛利计算超出有效数值范围。")
            continue
        result["products"].append({"name": name, "unit": unit, "price": price,
            "cost": cost, "gross_margin": margin, "scope": scope, "source_url": source,
            "price_page": price_row.get("page"), "cost_page": cost_row.get("page")})

    if result["products"]:
        warnings.append("单位毛利为同口径披露售价减综合单位销售成本，不是归母净利润；不同产品不加总。")
    if any(row.get("verification") == "announcement_text_checked" for row in result["records"]):
        warnings.append("来源经正式公告原文文本核对，报告PDF页面尚未完成视觉核验。")
    return result
