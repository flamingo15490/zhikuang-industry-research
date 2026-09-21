"""工具注册表：把有色分析能力暴露给 LLM（OpenAI function calling 格式）。"""
from __future__ import annotations

from tools.aluminum_spread import ALUMINUM_PROFIT_TOOL, get_aluminum_profit
from tools.capital_flow import CAPITAL_FLOW_TOOL, get_capital_flow
from tools.company_profile import COMPANY_PROFILE_TOOL, get_company_profile
from tools.financial import FINANCIAL_INDICATORS_TOOL, get_financial_indicators
from tools.live_data import METAL_PRICE_TOOL, QUOTE_TOOL, get_metal_price, get_realtime_quote
from tools.macro_state import MACRO_STATE_TOOL, query_macro_state
from tools.price_sensitivity import PRICE_SENSITIVITY_TOOL, estimate_price_sensitivity
from tools.profit_analysis import PROFIT_ANALYSIS_TOOL, get_profit_analysis
from tools.profit_scenarios import PROFIT_SCENARIO_TOOL, calculate_profit_scenario
from tools.risk_scan import RISK_SCAN_TOOL, scan_risk
from tools.sector_matrix import SECTOR_MATRIX_TOOL, sector_impact_matrix
from tools.sector_overview import SECTOR_TOOL, list_sector_stocks
from tools.technical import TECHNICAL_TOOL, get_technical_indicator
from tools.valuation import VALUATION_TOOL, get_stock_fundamentals

TOOLS = [
    MACRO_STATE_TOOL,
    VALUATION_TOOL,
    FINANCIAL_INDICATORS_TOOL,
    SECTOR_TOOL,
    COMPANY_PROFILE_TOOL,
    PRICE_SENSITIVITY_TOOL,
    QUOTE_TOOL,
    METAL_PRICE_TOOL,
    TECHNICAL_TOOL,
    CAPITAL_FLOW_TOOL,
    RISK_SCAN_TOOL,
    SECTOR_MATRIX_TOOL,
    ALUMINUM_PROFIT_TOOL,
    PROFIT_ANALYSIS_TOOL,
    PROFIT_SCENARIO_TOOL,
]

_TOOL_FUNCS = {
    "query_macro_state": query_macro_state,
    "get_stock_fundamentals": get_stock_fundamentals,
    "get_financial_indicators": get_financial_indicators,
    "list_sector_stocks": list_sector_stocks,
    "get_company_profile": get_company_profile,
    "estimate_price_sensitivity": estimate_price_sensitivity,
    "get_realtime_quote": get_realtime_quote,
    "get_metal_price": get_metal_price,
    "get_technical_indicator": get_technical_indicator,
    "get_capital_flow": get_capital_flow,
    "scan_risk": scan_risk,
    "sector_impact_matrix": sector_impact_matrix,
    "get_aluminum_profit": get_aluminum_profit,
    "get_profit_analysis": get_profit_analysis,
    "calculate_profit_scenario": calculate_profit_scenario,
}


def execute_tool(name: str, args: dict) -> str:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return f"错误：未知工具 {name}"
    try:
        return fn(**args)
    except TypeError as exc:
        return f"错误：工具参数不匹配——{exc}"
    except Exception as exc:  # noqa: BLE001
        return f"错误：工具执行失败 {type(exc).__name__}: {exc}"
