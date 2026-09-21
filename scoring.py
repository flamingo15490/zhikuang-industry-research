"""Versioned research observations, with explicit missing-data propagation."""
from __future__ import annotations

import math
from numbers import Real


VERSION = '2.0'
DIMS = ['基本面', '估值', '技术面', '资金面', '安全度']
REQUIRED = {
    '基本面': ('roe', 'growth'),
    '估值': ('pe',),
    '技术面': ('ma5', 'ma20', 'ma60', 'dif', 'dea', 'rsi', 'return20'),
    '资金面': ('flow_ratio_pct',),
    '安全度': ('debt', 'growth', 'current'),
}
UNITS = {
    'roe': '%', 'growth': '%', 'pe': '倍',
    'ma5': '元', 'ma20': '元', 'ma60': '元', 'dif': '元', 'dea': '元',
    'rsi': '指数点', 'return20': '%', 'flow_ratio_pct': '%',
    'debt': '%', 'current': '倍',
}
GROWTH_RULE = '增长率<-20%:10分；[-20%,0%):30分；=0%:50分；(0%,20%):70分；>=20%:90分。'
TREND_RULE = 'MA5>MA20>MA60加15分；MA5<MA20<MA60减15分；其余含任意相等加0分，整组仅计一次。'
MACD_RULE = 'DIF>DEA加10分；DIF<DEA减10分；相等加0分，整组仅计一次。'
RULES = {
    'roe': 'ROE<0%:0分；=0%:20分；(0%,5%):40分；[5%,10%):60分；[10%,15%):80分；>=15%:100分。',
    'growth': GROWTH_RULE,
    'pe': '仅正PE：<10倍90分；[10,15)倍75分；[15,20)倍60分；[20,30)倍45分；>=30倍30分；PE<=0不适用。',
    'ma5': TREND_RULE, 'ma20': TREND_RULE, 'ma60': TREND_RULE,
    'dif': MACD_RULE, 'dea': MACD_RULE,
    'rsi': '40<RSI<60加5分；RSI<30或RSI>70减5分；其余含30/40/60/70边界加0分。',
    'return20': '20日收益率>0%加10分；<0%减10分；=0%加0分。',
    'flow_ratio_pct': '五日净流入/同五日成交额×100%；50+4×比率，最低10分、最高90分；0%为50分。',
    'debt': '资产负债率<40%:90分；[40%,60%]:70分；(60%,70%]:50分；>70%:20分。',
    'current': '流动比率<1:20分；=1:50分；(1,2):70分；>=2:90分。',
}


def _value(raw: dict, key: str) -> tuple[float | None, str | None]:
    value = raw.get(key)
    if value is None:
        return None, 'missing'
    if isinstance(value, bool) or not isinstance(value, Real):
        return None, 'invalid_type'
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return None, 'nonfinite'
    if not math.isfinite(value):
        return None, 'nonfinite'
    if (key in ('ma5', 'ma20', 'ma60') and value <= 0
            or key == 'rsi' and not 0 <= value <= 100
            or key in ('debt', 'current') and value < 0
            or key == 'return20' and value < -100):
        return None, 'invalid_domain'
    return value, None


def _growth(value: float) -> float:
    if value < -20:
        return 10.
    if value < 0:
        return 30.
    if value == 0:
        return 50.
    return 70. if value < 20 else 90.


def _component(key: str, value: float) -> float:
    if key == 'growth':
        return _growth(value)
    if key == 'roe':
        if value < 0:
            return 0.
        if value == 0:
            return 20.
        return 40. if value < 5 else 60. if value < 10 else 80. if value < 15 else 100.
    if key == 'pe':
        return 90. if value < 10 else 75. if value < 15 else 60. if value < 20 else 45. if value < 30 else 30.
    if key == 'debt':
        return 90. if value < 40 else 70. if value <= 60 else 50. if value <= 70 else 20.
    if key == 'current':
        return 20. if value < 1 else 50. if value == 1 else 70. if value < 2 else 90.
    raise ValueError(f'Unknown component: {key}')


def score_observation(raw: dict) -> dict:
    """Score normalized observations; rates are percent values, not fractions.

    No IO, peer normalization or imputation. The collector owns periods, source
    validity, growth-base eligibility and sufficient market-data history.
    """
    if not isinstance(raw, dict):
        raise TypeError('raw must be a dict')
    normalized = {key: _value(raw, key) for key in UNITS}
    values = {key: pair[0] for key, pair in normalized.items()}
    dimensions = {}
    for dimension, keys in REQUIRED.items():
        metrics = [dict(key=key, value=values[key], unit=UNITS[key], rule=RULES[key],
                        invalid_reason=normalized[key][1]) for key in keys]
        missing = [key for key in keys if values[key] is None]
        result = dict(score=None, status='missing', metrics=metrics, missing=missing,
                      reason='缺失或无效输入：' + ', '.join(missing),
                      label='估值观察' if dimension == '估值' else dimension)
        dimensions[dimension] = result
        if missing:
            continue
        if dimension == '估值' and values['pe'] <= 0:
            result.update(status='not_applicable', reason='PE非正，亏损或零利润口径下不适用正PE分档。')
            continue

        if dimension in ('基本面', '安全度', '估值'):
            weights = ({'roe': .7, 'growth': .3} if dimension == '基本面'
                       else {'debt': .4, 'growth': .3, 'current': .3} if dimension == '安全度'
                       else {'pe': 1.})
            for metric in metrics:
                key = metric['key']
                metric.update(score=_component(key, values[key]), weight=weights[key])
                metric['contribution'] = round(metric['score'] * metric['weight'], 6)
            score = math.fsum(metric['contribution'] for metric in metrics)
            reason = ('ROE绝对分档70%+净利润增长分档30%。' if dimension == '基本面'
                      else '债率40%+增长30%+流动比率30%；披露质量单独展示。' if dimension == '安全度'
                      else '正PE分档观察，不表示周期行业便宜或公允价值。')
        elif dimension == '资金面':
            score = 50. + 4. * max(-10., min(10., values['flow_ratio_pct']))
            metrics[0].update(score=score, weight=1., contribution=score)
            reason = '使用同五个交易日的资金净流入/成交额比率，不使用绝对金额。'
        else:
            ma5, ma20, ma60 = (values[key] for key in ('ma5', 'ma20', 'ma60'))
            trend = 15. if ma5 > ma20 > ma60 else -15. if ma5 < ma20 < ma60 else 0.
            macd = 10. if values['dif'] > values['dea'] else -10. if values['dif'] < values['dea'] else 0.
            rsi = values['rsi']
            rsi_delta = 5. if 40 < rsi < 60 else -5. if rsi < 30 or rsi > 70 else 0.
            momentum = 10. if values['return20'] > 0 else -10. if values['return20'] < 0 else 0.
            # Coupled indicators attach their contribution once, at the first key.
            deltas = dict(ma5=trend, ma20=0., ma60=0., dif=macd, dea=0.,
                          rsi=rsi_delta, return20=momentum)
            for metric in metrics:
                metric['delta'] = deltas[metric['key']]
            score = 50. + math.fsum(deltas.values())
            result['base_score'] = 50.
            reason = '基准50分+均线排列+MACD比较+RSI区间+20日收益方向，各项加减分见指标。'
        result.update(score=round(score, 6), status='complete', reason=reason)

    scores = {dimension: result['score'] for dimension, result in dimensions.items()}
    completed = sum(result['status'] == 'complete' for result in dimensions.values())
    eligible = completed == len(DIMS)
    return dict(version=VERSION, scores=scores, dimensions=dimensions,
                composite=round(math.fsum(scores.values()) / len(DIMS), 6) if eligible else None,
                coverage=completed / len(DIMS), eligible=eligible)
