"""工具8：技术面指标（腾讯日K源）。均线、MACD、RSI、近20日涨跌。"""
from __future__ import annotations

import json
import math
from datetime import date
import urllib.request

from tools._resolve import resolve_stock
from tools.live_data import _normalize_code

TECHNICAL_TOOL = {
    "type": "function",
    "function": {
        "name": "get_technical_indicator",
        "description": (
            "计算个股技术面：MA5/20/60 均线及排列、MACD、RSI(14)、近20日涨跌幅。"
            "基于腾讯前复权日K，接口失败时可使用带日期的近期本地行情快照并明确标注。仅供形态参考，不构成买卖建议。输入股票代码或名称。"
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


def _fetch_kline(sym: str, n: int = 120) -> list[list]:
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{n},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
    node = json.loads(txt)["data"][sym]
    if not node.get('qfqday'):
        raise ValueError('前复权日K缺失，不能以未复权行情替代')
    return node['qfqday']


def _cached_kline(code):
    # Lazy import avoids the scoring collector's dependency on these indicators.
    from score_view import read_snapshot
    snapshot = read_snapshot()
    if not snapshot or date.fromisoformat(snapshot['as_of']) > date.today():
        raise ValueError('没有可用的本地行情快照')
    matches = [row for row in snapshot['rows'] if row.get('code') == code]
    if len(matches) != 1:
        raise ValueError('本地行情公司记录不唯一或缺失')
    row = matches[0]
    if any(row.get(key) != snapshot[key] for key in ('batch_id', 'version', 'as_of', 'financial_period')):
        raise ValueError('本地行情批次不一致')
    raw = row['raw']
    if any(raw.get(key) != row[key] for key in ('code', 'as_of', 'financial_period')):
        raise ValueError('本地行情对象或期间不一致')
    detail = raw['source_details']['technical']
    if detail.get('adjustment') != 'qfq' or detail.get('data_field', 'qfqday') != 'qfqday':
        raise ValueError('本地行情复权口径不适用')
    rows = sorted(detail['rows'], key=lambda item: item[0])
    dates = [date.fromisoformat(item[0]) for item in rows]
    if len(rows) < 60 or len(set(dates)) != len(rows):
        raise ValueError('本地行情长度不足或日期重复')
    if (dates[-1].isoformat() != raw.get('market_date')
            or dates[-1].isoformat() != raw['source_dates'].get('technical')
            or dates[-1] > date.fromisoformat(snapshot['as_of'])
            or not 0 <= (date.today() - dates[-1]).days <= 4):
        raise ValueError('本地行情已过期或日期不一致')
    if any(not math.isfinite(float(item[2])) or float(item[2]) <= 0 for item in rows):
        raise ValueError('本地收盘价无效')
    return rows, snapshot['batch_id']


def _ema_series(vals: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _ma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if ag == 0 and al == 0:
        return 50.0
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def get_technical_indicator(code: str) -> str:
    try:
        name, c = resolve_stock(code)
        sym = _normalize_code(c if c else code)
        source_note = '腾讯前复权日K'
        fallback_note = ''
        try:
            k = _fetch_kline(sym, 120)
            if len(k) < 60:
                raise ValueError('实时K线不足60根')
        except Exception as live_error:
            try:
                k, batch = _cached_kline(c)
            except Exception as cache_error:
                raise ValueError(f'实时接口：{type(live_error).__name__}；本地回退：{cache_error}') from live_error
            source_note = '本地行情快照，腾讯前复权日K'
            fallback_note = f'- 实时接口不可用（{type(live_error).__name__}），使用截至{k[-1][0]}的已保存行情；不是本次实时获取。快照批次：{batch}。'
        closes = [float(x[2]) for x in k]
        last = closes[-1]
        ma5, ma20, ma60 = _ma(closes, 5), _ma(closes, 20), _ma(closes, 60)
        ema12, ema26 = _ema_series(closes, 12), _ema_series(closes, 26)
        dif = [a - b for a, b in zip(ema12, ema26)]
        dea = _ema_series(dif, 9)
        hist = (dif[-1] - dea[-1]) * 2
        rsi14 = _rsi(closes)
        chg20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else None

        if ma5 and ma20 and ma60:
            arrange = ("多头排列（MA5>MA20>MA60）" if ma5 > ma20 > ma60
                       else "空头排列（MA5<MA20<MA60）" if ma5 < ma20 < ma60
                       else "均线纠缠/震荡")
        else:
            arrange = "数据不足"

        rsi_txt = ("超买" if rsi14 > 70 else "超卖" if rsi14 < 30 else "中性") if rsi14 is not None else "NA"
        lines = [
            f"{name or code} 技术面（截至 {k[-1][0]}，{source_note}）：",
            *([fallback_note] if fallback_note else []),
            f"- 收盘 {last}，MA5 {ma5:.2f} / MA20 {ma20:.2f} / MA60 {ma60:.2f}",
            f"- 均线形态：{arrange}",
            f"- MACD：DIF {dif[-1]:.3f}，DEA {dea[-1]:.3f}，柱 {hist:+.3f}（{'多头' if dif[-1] > dea[-1] else '空头'}）",
            f"- RSI(14)：{rsi14:.1f}（{rsi_txt}）" if rsi14 is not None else "- RSI(14)：NA",
            f"- 近20日涨跌幅：{chg20:+.1f}%" if chg20 is not None else "- 近20日涨跌幅：NA",
            "⚠️ 技术指标仅供形态参考，不构成买卖建议。",
        ]
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"技术面获取失败：{type(exc).__name__}: {exc}"
