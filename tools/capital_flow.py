"""工具9：资金面（新浪资金流源）。主力/净流入。"""
from __future__ import annotations

import json
import urllib.request

from tools._resolve import resolve_stock
from tools.live_data import _normalize_code

CAPITAL_FLOW_TOOL = {
    "type": "function",
    "function": {
        "name": "get_capital_flow",
        "description": (
            "查询个股近期资金流：每日净流入、主力净流入，及近5日主力累计净流入。"
            "新浪资金流源，单位为元（自动换算成亿）。仅供资金面参考，不构成买卖建议。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码或名称，如 601899 / 紫金矿业"}
            },
            "required": ["code"],
        },
    },
}


def _yi(v) -> str:
    try:
        return f"{float(v)/1e8:+.2f} 亿"
    except (TypeError, ValueError):
        return "NA"


def get_capital_flow(code: str) -> str:
    try:
        name, c = resolve_stock(code)
        sym = _normalize_code(c if c else code)
        url = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"MoneyFlow.ssl_qsfx_zjlrqs?page=1&num=10&sort=opendate&asc=0&daima={sym}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
        txt = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        data = json.loads(txt)
        if not data:
            return f"{name or code}：未获取到资金流数据。"
        recent = data[:5]
        sum_r0 = sum(float(x.get("r0_net", 0) or 0) for x in recent)
        lines = [f"{name or code} 资金流（近{len(recent)}日，新浪源）："]
        for x in recent:
            lines.append(
                f"- {x.get('opendate')}：涨跌 {float(x.get('changeratio', 0))*100:+.2f}%，"
                f"净流入 {_yi(x.get('netamount'))}，主力净流入 {_yi(x.get('r0_net'))}"
            )
        lines.append(f"- 近{len(recent)}日主力累计净流入：{sum_r0/1e8:+.2f} 亿")
        lines.append("⚠️ 资金流仅供参考，不构成买卖建议。")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"资金流获取失败：{type(exc).__name__}: {exc}"
