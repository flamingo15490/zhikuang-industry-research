"""Auditable company profit bridges and disclosed segment comparisons."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

from ._resolve import resolve_stock

BASE = Path(__file__).resolve().parent.parent

PROFIT_ANALYSIS_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_profit_analysis',
        'description': '查询公司财报绝对金额：营业收入、营业成本、毛利、净利润及归母净利润；返回原始元计financial_metrics、报告期、来源及利润桥。金额查询和财报同业比较优先使用本工具；增长率/ROE等比率才用财务指标工具。保留缺失与勾稽异常。',
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '明确的股票代码或名称；对象不明确时先澄清'},
            'period': {'type': 'string', 'description': '可选报告期末日YYYY-MM-DD；用户明确指定期间时传入，未指定时采用当前缓存同口径期间'}}, 'required': ['query']},
    },
}

# Eastmoney impairment fields are signed gains/losses, not unsigned expenses.
DETAILS = [
    ('营业税金及附加', ('OPERATE_TAX_ADD',), -1),
    ('销售费用', ('SALE_EXPENSE',), -1),
    ('管理费用', ('MANAGE_EXPENSE',), -1),
    ('研发费用', ('RESEARCH_EXPENSE',), -1),
    ('财务费用', ('FINANCE_EXPENSE',), -1),
    ('其他收益', ('OTHER_INCOME',), 1),
    ('投资收益', ('INVEST_INCOME',), 1),
    ('公允价值变动收益', ('FAIRVALUE_CHANGE_INCOME',), 1),
    ('信用减值损益', ('CREDIT_IMPAIRMENT_INCOME',), 1),
    ('资产减值损益', ('ASSET_IMPAIRMENT_INCOME',), 1),
    ('资产处置收益', ('ASSET_DISPOSAL_INCOME',), 1),
    ('汇兑收益', ('EXCHANGE_INCOME',), 1),
    ('净敞口套期收益', ('NET_EXPOSURE_INCOME',), 1),
    ('营业外收入', ('NONBUSINESS_INCOME',), 1),
    ('营业外支出', ('NONBUSINESS_EXPENSE',), -1),
]


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _date(value):
    value = pd.to_datetime(value, errors='coerce')
    return None if pd.isna(value) else value.strftime('%Y-%m-%d')


def _text(value):
    return None if value is None or pd.isna(value) else str(value)


def _close(a, b, relative=0.0001):
    return abs(a - b) <= max(1., abs(a) * relative, abs(b) * relative)


def _eligible(df, date_column, require_notice=False):
    if date_column not in df:
        return df.iloc[0:0].copy()
    result = df.copy()
    result['_period'] = result[date_column].map(_date)
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    result = result[result['_period'].notna() & (result['_period'] <= today)]
    if 'NOTICE_DATE' in result:
        result['_notice'] = result['NOTICE_DATE'].map(_date)
        result = result[result['_notice'].notna() & (result['_notice'] <= today)]
    elif require_notice:
        return result.iloc[0:0]
    else:
        result['_notice'] = None
    return result.sort_values(['_period', '_notice'], ascending=False, na_position='last')


def _bridge(row, out):
    b = out['bridge']
    def add(label, value, measure='relative', origin='reported'):
        b['labels'].append(label)
        b['values'].append(value / 1e8)
        b['measures'].append(measure)
        b['origins'].append(origin)

    values = out['statement']
    revenue, cost = values.get('OPERATE_INCOME'), values.get('OPERATE_COST')
    out['bridge_status'] = 'partial'
    if revenue is None:
        out['warnings'].append('营业收入未披露，无法构建利润桥。')
        out['bridge_status'] = 'missing'
        return
    add('营业收入', revenue, 'absolute')
    if cost is None:
        out['warnings'].append('营业成本未披露，利润桥止于营业收入。')
        return
    gross = revenue - cost
    values['GROSS_PROFIT'] = gross
    add('营业成本', -cost)
    add('毛利', gross, 'total', 'derived')
    total = values.get('TOTAL_PROFIT')
    if total is None:
        out['warnings'].append('利润总额未披露，利润桥止于毛利。')
        return
    subtotal = gross
    missing = []
    operating = values.get('OPERATE_PROFIT')
    nonbusiness_income = values.get('NONBUSINESS_INCOME')
    nonbusiness_expense = values.get('NONBUSINESS_EXPENSE')
    can_check_total = all(v is not None for v in (operating, nonbusiness_income, nonbusiness_expense))
    for label, keys, sign in DETAILS:
        if can_check_total and keys[0] in ('NONBUSINESS_INCOME', 'NONBUSINESS_EXPENSE'):
            continue
        value = next((values.get(k) for k in keys if values.get(k) is not None), None)
        if value is None and keys[0] in ('ASSET_IMPAIRMENT_INCOME', 'CREDIT_IMPAIRMENT_INCOME'):
            old_value = values.get(keys[0].replace('_INCOME', '_LOSS'))
            value = -old_value if old_value is not None else None
        if value is None:
            missing.append(label)
        else:
            add(label, value * sign)
            subtotal += value * sign
    residual = (operating if can_check_total else total) - subtotal
    add('未分类损益差额', residual, origin='derived')
    out['reconciliation']['unclassified_income'] = residual
    inconsistent = False
    if can_check_total:
        add('营业利润', operating, 'total')
        add('营业外收入', nonbusiness_income)
        add('营业外支出', -nonbusiness_expense)
        expected_total = operating + nonbusiness_income - nonbusiness_expense
        difference = total - expected_total
        out['reconciliation']['operating_to_total'] = difference
        if difference:
            inconsistent = not _close(total, expected_total, relative=1e-10)
            add('利润总额勾稽差异' if inconsistent else '利润总额舍入差异', difference, origin='reconciliation')
            if inconsistent:
                out['warnings'].append(f'营业利润加营业外净收支与利润总额不一致：差 {difference:,.2f} 元。')
    out['reconciliation']['total_profit'] = out['reconciliation'].get('operating_to_total', 0.)
    out['missing_details'] = missing
    if missing:
        out['warnings'].append('未单独披露的损益项目：' + '、'.join(missing) + '；未分类损益差额为报表差额推导，不能视作已披露费用。')
    add('利润总额', total, 'total')
    previous = total
    for field, endpoint, label, endlabel, key in [
        ('INCOME_TAX', 'NETPROFIT', '所得税', '净利润', 'net_profit'),
        ('MINORITY_INTEREST', 'PARENT_NETPROFIT', '少数股东损益', '归母净利润', 'parent_net_profit'),
    ]:
        deduction, reported = values.get(field), values.get(endpoint)
        if deduction is None or reported is None:
            out['warnings'].append(f'{label}或{endlabel}未披露，利润桥止于上一已核验终点。')
            out['bridge_status'] = 'inconsistent' if inconsistent else 'partial'
            return
        add(label, -deduction)
        difference = reported - (previous - deduction)
        out['reconciliation'][key] = difference
        if not _close(reported, previous - deduction, relative=1e-10):
            add(endlabel + '勾稽差异', difference, origin='reconciliation')
            out['warnings'].append(f'{endlabel}勾稽不一致：披露值与计算值差 {difference:,.2f} 元。')
            inconsistent = True
        elif difference != 0:
            add(endlabel + '舍入差异', difference, origin='reconciliation')
        add(endlabel, reported, 'total')
        previous = reported
    out['bridge_status'] = 'inconsistent' if inconsistent else 'complete'


def _business_types(names):
    rules = [
        ('mining', r'矿山|采选|采矿|锂矿|矿产'),
        ('smelting', r'外购精矿|(?i:TC\s*[/／]\s*RC)|加工费.*冶炼|冶炼.*加工费'),
        ('aluminum', r'电解铝|原铝'),
        ('processing', r'加工|板带|卷板|铜杆|铜线|铝箔|(?<!原)铝板(?!块)|铝型材|钛材|磁材|磁性材料|功能材料|新材料|合金'),
        ('refining', r'锂盐|锂化合物|碳酸锂|氢氧化锂|稀土分离|分离产品|镍盐|钴盐|化合物'),
        ('recycling', r'再生|回收|循环利用'),
        ('trading', r'贸易|供应链|供给服务'),
    ]
    return [key for key, pattern in rules if any(re.search(pattern, name)
        and not (key == 'mining' and re.search(r'工程|机械|设备|设计|咨询|运营管理|承包|服务', name))
        for name in names)]


def _common_period(code, periods):
    path = BASE / 'data/company_profile' / f'zy_{code}.parquet'
    if not path.exists():
        return None
    try:
        df = _eligible(pd.read_parquet(path), '报告日期')
        if '分类类型' not in df or '主营构成' not in df:
            return None
        df = df[df['分类类型'].isin(['按产品分类', '按行业分类']) & df['主营构成'].notna()]
        common = set(periods).intersection(df['_period'])
        return max(common) if common else None
    except (OSError, ValueError):
        return None


def _segments(code, out):
    path = BASE / 'data/company_profile' / f'zy_{code}.parquet'
    out['segment_source'] = {'path': str(path), 'url': None, 'notice_date': None,
                             'notice_date_status': 'unavailable'}
    if not path.exists():
        out['warnings'].append('主营构成缓存缺失。')
        return
    try:
        df = _eligible(pd.read_parquet(path), '报告日期')
    except (ValueError, OSError) as exc:
        out['warnings'].append(f'主营构成缓存不可读：{exc}')
        return
    if df.empty or '分类类型' not in df or '主营构成' not in df:
        return
    df = df[df['分类类型'].isin(['按产品分类', '按行业分类'])]
    if df.empty:
        return
    period = out['period'] if out['period'] in set(df['_period']) else df['_period'].max()
    df = df[df['_period'] == period]
    dimension = '按产品分类' if (df['分类类型'] == '按产品分类').any() else '按行业分类'
    df = df[df['分类类型'] == dimension]
    out['segment_period'] = period
    out['warnings'].append('主营构成缓存未提供公告日期和原公告链接，无法核验分部披露时点。')
    has_structure = False
    seen = set()
    for _, row in df.iterrows():
        name = _text(row.get('主营构成')) or ''
        revenue, cost, reported = (_number(row.get(k)) for k in ['主营收入', '主营成本', '主营利润'])
        gross = revenue - cost if revenue is not None and cost is not None else None
        excluded, reason, status = False, '', 'complete'
        child = bool(re.search(r'^\s*其中\s*[:：]?|^\s*\d+[.、]', name))
        total = bool(re.fullmatch(r'(合计|总计|营业收入|主营业务合计|主营业务收入|总收入)', name.strip()))
        elimination = bool(re.search(r'抵销|抵消|内部交易|内部销售', name))
        if child or total or name in seen or not name.strip():
            excluded, status = True, 'excluded'
            reason = '子项' if child else '汇总行' if total else '重复标签或无效标签'
        elif gross is None:
            status, reason = 'missing', '收入或成本未披露，无法计算毛利'
        elif reported is not None and not _close(gross, reported):
            excluded, status, reason = True, 'inconsistent', '收入减成本与披露利润不一致'
        if elimination:
            reason = (reason + '；' if reason else '') + '内部抵销，保留原始符号，仅单独比较'
        has_structure |= child or total or elimination or name in seen
        seen.add(name)
        out['segments'].append(dict(name=name, classification=dimension, revenue=revenue,
            cost=cost, gross_profit=gross, reported_profit=reported,
            margin=gross / revenue if gross is not None and revenue and revenue > 0 else None,
            contribution=None, status=status, excluded=excluded, reason=reason,
            is_elimination=elimination, period=period, units='元', origin='derived'))
    out['business_types'] = _business_types([r['name'] for r in out['segments'] if not r['excluded']])
    if period != out['period']:
        out['segment_status'] = 'period_mismatch'
        out['warnings'].append(f'分部期间 {period} 与公司报表期间 {out["period"]} 不同，禁止跨期贡献汇总。')
        return
    out['segment_status'] = 'comparison_only'
    rows = out['segments']
    statement = out['statement']
    if not rows or has_structure or any(r['excluded'] or r['gross_profit'] is None for r in rows):
        return
    totals = {k: sum(r[k] for r in rows) for k in ('revenue', 'cost', 'gross_profit')}
    for key, field in [('revenue', 'OPERATE_INCOME'), ('cost', 'OPERATE_COST'), ('gross_profit', 'GROSS_PROFIT')]:
        if statement.get(field) is None or not _close(totals[key], statement[field]):
            out['warnings'].append('分部收入、成本或毛利无法与合并报表完整勾稽，仅展示分部比较。')
            return
    out['segment_status'] = 'verified'
    out['segment_totals'] = totals
    if totals['gross_profit'] > max(1., abs(totals['revenue']) * 1e-8):
        for row in rows:
            row['contribution'] = row['gross_profit'] / totals['gross_profit']


def analyze_profit(query: str, period: str | None = None) -> dict:
    """Return reported/derived actuals; statement and segment amounts are yuan."""
    out = dict(code=None, name=None, period=None, periods=[], notice_date=None,
        source={}, bridge=dict(labels=[], values=[], measures=[], origins=[], units='亿元'),
        statement={}, reconciliation={}, missing_details=[], bridge_status='missing',
        segments=[], segment_period=None, segment_status='missing', segment_totals=None,
        segment_source={}, business_types=[], warnings=[], summary='')
    if not str(query).strip():
        out['summary'] = '请输入股票代码或名称。'
        return out
    try:
        name, code = resolve_stock(query)
    except (OSError, ValueError) as exc:
        out['summary'] = f'公司索引不可用：{exc}'
        return out
    if code is None:
        out['summary'] = f'未找到股票：{query}'
        return out
    out.update(name=name, code=code)
    frames = []
    for kind, folder in [('complete', 'profit_analysis'), ('annual_fallback', 'company_profile')]:
        path = BASE / 'data' / folder / f'profit_{code}.parquet'
        if not path.exists():
            continue
        try:
            frame = _eligible(pd.read_parquet(path), 'REPORT_DATE', require_notice=True)
        except (ValueError, OSError) as exc:
            out['warnings'].append(f'利润表缓存不可读：{exc}')
            continue
        frame['_path'], frame['_kind'] = str(path), kind
        frames.append(frame)
    if frames:
        df = pd.DataFrame([row for frame in frames for row in frame.to_dict('records')])
        if df.empty:
            df = pd.DataFrame(columns=['_period'])
        df = df.drop_duplicates('_period', keep='first')
        out['periods'] = sorted(df['_period'].dropna().unique().tolist(), reverse=True)
        selected = _date(period) if period is not None else (out['periods'][0] if out['periods'] else None)
        if period is None:
            selected = _common_period(code, out['periods']) or selected
        match = df[df['_period'] == selected]
        if not match.empty:
            row = match.iloc[0]
            out.update(period=selected, notice_date=row['_notice'])
            out['source'] = dict(path=row['_path'], kind=row['_kind'],
                url=_text(row.get('source_url')), fetched_at=_text(row.get('fetched_at')))
            out['statement'] = {str(k): _number(v) for k, v in row.items() if str(k).isupper() and k not in ('REPORT_DATE', 'NOTICE_DATE', 'REPORT_DATE_NAME')}
            if row['_kind'] == 'annual_fallback':
                out['warnings'].append('采用原年报简表缓存，未披露的损益明细保留缺失。')
            _bridge(row, out)
    if out['period'] is None:
        out['warnings'].append('指定期间无可用且已公告的利润表。' if period is not None else '没有已公告的可用利润表。')
    _segments(code, out)
    labels = {'complete': '完整', 'partial': '部分数据', 'missing': '缺失', 'inconsistent': '勾稽异常'}
    out['summary'] = f'{name}（{code}），财报期间 {out["period"] or "无"}，利润桥：{labels[out["bridge_status"]]}；分部期间 {out["segment_period"] or "无"}，状态 {out["segment_status"]}。'
    return out


def format_profit_summary(analysis: dict) -> str:
    """Compact shared report/tool view; raw statements remain in analyze_profit."""
    out = {k: analysis.get(k) for k in ('code', 'name', 'period', 'notice_date',
        'bridge_status', 'segment_period', 'segment_status', 'business_types', 'summary')}
    source = analysis.get('source', {})
    out['source'] = {k: source.get(k) for k in ('kind', 'url', 'fetched_at')}
    statement = analysis.get('statement') or {}
    out['financial_metrics'] = {
        key: {'value': statement.get(field), 'unit': '元', 'origin': origin}
        for key, field, origin in (
            ('revenue', 'OPERATE_INCOME', 'reported'),
            ('operating_cost', 'OPERATE_COST', 'reported'),
            ('gross_profit', 'GROSS_PROFIT', 'derived'),
            ('net_profit', 'NETPROFIT', 'reported'),
            ('parent_netprofit', 'PARENT_NETPROFIT', 'reported'))}
    bridge = analysis.get('bridge', {})
    out['bridge_units'] = bridge.get('units', '亿元')
    out['bridge'] = [dict(name=name, value=round(value, 6), origin=origin)
        for name, value, origin in zip(bridge.get('labels', []), bridge.get('values', []), bridge.get('origins', []))]
    segments = analysis.get('segments', [])
    out['segments_units'] = '亿元'
    out['segments'] = [dict(name=r['name'], gross_profit=None if r['gross_profit'] is None else round(r['gross_profit'] / 1e8, 6),
        status=r['status'], excluded=r['excluded']) for r in segments[:24]]
    if len(segments) > 24:
        out['segments_omitted'] = len(segments) - 24
    out['warnings'] = analysis.get('warnings', [])
    return json.dumps(out, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def get_profit_analysis(query: str, period: str | None = None) -> str:
    return format_profit_summary(analyze_profit(query, period=period))
