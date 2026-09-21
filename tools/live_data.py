"""工具6/7：运行时联网获取（实时行情 + 商品价格）。

与本地缓存数据不同，这些工具在运行时实时抓取网络数据，可能随市场变化。
返回结果标注"实时数据，仅供当前时点参考，不可复现"，与点时性财报数据严格区分。
"""
from __future__ import annotations

import urllib.request

_UA = {"User-Agent": "Mozilla/5.0"}

QUOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_realtime_quote",
        "description": (
            "获取 A 股实时行情快照：最新价、涨跌幅、成交额、换手率、市盈率、总市值等。"
            "实时数据，仅供当前时点参考，不可复现。输入股票代码如 601899 / sh601899 / sh.601899。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "股票代码，如 601899、sh601899、sh.601899"}
            },
            "required": ["code"],
        },
    },
}

METAL_PRICE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_metal_price",
        "description": (
            "获取金属外盘最新报价（伦敦金/伦敦银/伦铜/伦铝/伦锌/伦镍/伦锡/伦铅）。"
            "实时数据，仅供当前时点参考，不可复现。输入金属名，如 gold/silver/copper 或 黄金/白银/铜。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metal": {"type": "string", "description": "金属名：gold/silver/copper/aluminum/zinc/nickel/tin/lead 或中文"}
            },
            "required": ["metal"],
        },
    },
}

_SINA_METALS = {
    "gold": "hf_XAU", "黄金": "hf_XAU", "金": "hf_XAU",
    "silver": "hf_XAG", "白银": "hf_XAG", "银": "hf_XAG",
    "copper": "hf_CAD", "铜": "hf_CAD",
    "aluminum": "hf_ALI", "铝": "hf_ALI",
    "zinc": "hf_ZSD", "锌": "hf_ZSD",
    "nickel": "hf_NID", "镍": "hf_NID",
    "tin": "hf_SND", "锡": "hf_SND",
    "lead": "hf_PBD", "铅": "hf_PBD",
}


def _normalize_code(code: str) -> str:
    c = str(code).strip().lower().replace(".", "").replace(" ", "")
    if c[:2] in ("sh", "sz", "bj"):
        return c
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("0", "3")):
        return "sz" + c
    if c.startswith(("8", "4")):
        return "bj" + c
    return c


def _fetch(url: str, enc: str = "gbk", referer: str | None = None) -> str:
    headers = dict(_UA)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=12).read().decode(enc, errors="ignore")


def _yi_from_wan(value: str) -> str:
    try:
        return f"{float(value)/1e4:.2f} 亿"
    except (TypeError, ValueError):
        return "NA"


def get_realtime_quote(code: str) -> str:
    sym = _normalize_code(code)
    try:
        txt = _fetch(f"http://qt.gtimg.cn/q={sym}")
        payload = txt.split('="', 1)[1].rsplit('"', 1)[0]
        f = payload.split("~")
        if len(f) < 46 or not f[3]:
            return f"未获取到 {code} 的实时行情（请确认代码格式，如 601899 / 000060）"
        ts = f[30]
        dt = (f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
              if len(ts) >= 14 else ts)
        return "\n".join([
            f"{f[1]}（{f[2]}）实时行情（{dt}，腾讯源）：",
            f"- 最新价 {f[3]}，涨跌 {f[31]}（{f[32]}%）",
            f"- 今开 {f[5]}，最高 {f[33]}，最低 {f[34]}，昨收 {f[4]}",
            f"- 成交额 {_yi_from_wan(f[37])}，换手率 {f[38]}%",
            f"- 市盈率(TTM) {f[39]}，市净率 {f[46]}，总市值 {f[45]} 亿",
            "⚠️ 实时数据，仅供当前时点参考，不可复现。",
        ])
    except Exception as exc:  # noqa: BLE001
        return f"实时行情获取失败：{type(exc).__name__}: {exc}"


def get_metal_price(metal: str) -> str:
    key = _SINA_METALS.get(str(metal).strip().lower())
    if key is None:
        return ("暂不支持金属实时报价（支持 gold/silver/copper/aluminum/zinc/nickel/tin/lead "
                "或 黄金/白银/铜/铝/锌/镍/锡/铅）")
    try:
        txt = _fetch(f"http://hq.sinajs.cn/list={key}", referer="https://finance.sina.com.cn/")
        payload = txt.split('="', 1)[1].rsplit('"', 1)[0]
        p = payload.split(",")
        if len(p) < 14 or not p[0]:
            return f"未获取到 {metal} 的实时报价"
        return "\n".join([
            f"{p[13]} 实时报价（{p[12]} {p[6]}，新浪外盘）：",
            f"- 现价 {p[0]}，最高 {p[4]}，最低 {p[5]}",
            "⚠️ 实时外盘数据，仅供当前时点参考，不可复现。",
        ])
    except Exception as exc:  # noqa: BLE001
        return f"商品价格获取失败：{type(exc).__name__}: {exc}"
