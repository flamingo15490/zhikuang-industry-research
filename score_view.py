"""Snapshot-only score presentation. No live calls or legacy-cache fallback."""
from collections import Counter
from html import escape
import json
import math
from numbers import Real
from pathlib import Path
from urllib.parse import urlsplit

import plotly.graph_objects as go

from chart_style import C
from interaction import format_peer_ranking
from scoring import DIMS, VERSION

SNAPSHOT_PATH = Path(__file__).resolve().parent / 'data' / 'scoring' / 'current.json'
MARKET_DIMS = {'估值', '技术面', '资金面'}
LABELS = dict(roe='净资产收益率', growth='净利润增长率', pe='PE(TTM)', ma5='5日均线',
              ma20='20日均线', ma60='60日均线', dif='MACD DIF', dea='MACD DEA', rsi='RSI',
              return20='20日收益率', flow_ratio_pct='五日净流入/成交额', debt='资产负债率', current='流动比率')
METRIC_LABELS = {**LABELS, 'roe': '净资产收益率（净利润相对净资产）',
    'growth': '净利润同比增长率（相对上年同期）', 'pe': '市盈率（PE，价格相对每股盈利）',
    'dif': 'MACD快慢均线差（DIF）', 'dea': 'MACD差值平滑线（DEA）',
    'rsi': '相对强弱指标（RSI，近期涨跌强度）',
    'debt': '资产负债率（负债相对资产）', 'current': '流动比率（流动资产相对流动负债）'}
SOURCE_LABELS = {**METRIC_LABELS, 'technical': '技术指标行情', 'flow_amount': '五日成交额',
    'roe_verification': '净资产收益率复核', 'local_file': '本地来源文件',
    'report_period': '报告期', 'ann_date': '公告日', 'cached_value': '缓存观测值',
    'current_profit': '本期归母净利润', 'previous_profit': '上年同期归母净利润',
    'previous_period': '比较报告期', 'previous_ann_date': '比较期公告日', 'unit': '单位',
    'field': '供应商字段', 'value': '观测值', 'field_index': '供应商数值字段位置',
    'timestamp_field_index': '供应商日期字段位置', 'observed_pe': '观测市盈率',
    'trading_dates': '交易日期', 'close_unit': '收盘价单位', 'adjustment': '复权口径',
    'rows': '行情原始记录', 'historical_limit': '历史口径限制', 'raw_rows': '供应商原始记录',
    'required_dates': '要求的共同交易日', 'units_verified': '单位是否已核验',
    'amount_rows': '成交额记录', 'amount_unit_reference': '成交额单位参考',
    'normalized_rows': '日期对齐后的资金记录', 'date': '日期', 'amount': '成交额',
    'r0_net': '主力净流入', 'opendate': '交易日', 'ratio': '比例'}
STATUS = {'complete': '完整', 'missing': '缺失', 'not_applicable': '不适用'}
EN2CN = dict(copper='铜', aluminum='铝', gold='黄金', silver='白银', zinc='锌', lead='铅',
            tin='锡', nickel='镍', rare_earth='稀土', lithium='锂', cobalt='钴', tungsten='钨',
            molybdenum='钼', antimony='锑', germanium='锗', titanium='钛', platinum='铂', other='其他',
            industrial_metals='工业金属', precious_metals='贵金属', strategic_metals='战略金属')


def _header(snapshot):
    return (isinstance(snapshot, dict) and snapshot.get('schema_version') == 2
            and snapshot.get('version') == VERSION and isinstance(snapshot.get('rows'), list)
            and all(isinstance(snapshot.get(key), str) and snapshot[key].strip()
                    for key in ('batch_id', 'as_of', 'financial_period')))


def _invalid_json_number(value):
    raise ValueError(value)


def read_snapshot(path=None):
    try:
        with Path(path or SNAPSHOT_PATH).open(encoding='utf-8') as stream:
            snapshot = json.load(stream, parse_constant=_invalid_json_number)
        return snapshot if _header(snapshot) else None
    except (OSError, ValueError, TypeError):
        return None


def _rows(snapshot):
    if not _header(snapshot):
        return []
    rows = [row for row in snapshot['rows'] if isinstance(row, dict)
            and isinstance(row.get('code'), str) and row['code'].strip()
            and isinstance(row.get('stock_name'), str)
            and all(row.get(key) == snapshot[key] for key in ('batch_id', 'version', 'as_of', 'financial_period'))
            and isinstance(row.get('raw'), dict) and isinstance(row.get('scores'), dict)
            and row['scores'].get('version', VERSION) == VERSION]
    counts = Counter(row['code'] for row in rows)
    return [row for row in rows if counts[row['code']] == 1]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _dimension(row, dim):
    dimensions = row['scores'].get('dimensions')
    value = dimensions.get(dim, {}) if isinstance(dimensions, dict) else {}
    return value if isinstance(value, dict) else {}


def _score(row, dim):
    scores = row['scores'].get('scores')
    value = _number(scores.get(dim)) if isinstance(scores, dict) else None
    return value if value is not None and 0 <= value <= 100 and _dimension(row, dim).get('status') == 'complete' else None


def _composite(row):
    values = [_score(row, dim) for dim in DIMS]
    composite = _number(row['scores'].get('composite'))
    if (row['scores'].get('eligible') is not True or any(value is None for value in values)
            or composite is None or not math.isclose(composite, math.fsum(values) / 5, abs_tol=1e-6)):
        return None
    return composite


def _market_date(row):
    value = row['raw'].get('market_date')
    return value if isinstance(value, str) and value.strip() else None


def _bucket(rows, target):
    for key in ('subindustry', 'subindustry_group'):
        category = target.get(key)
        if isinstance(category, str) and category.strip():
            group = [row for row in rows if row.get(key) == category]
            if len(group) >= 3:
                return group, EN2CN.get(category, category)
    return rows, '全板块'


def _context(snapshot, target):
    bucket, name = _bucket(_rows(snapshot), target)
    market_date = _market_date(target)
    means, counts = {}, {}
    for dim in DIMS:
        values = [_score(row, dim) for row in bucket
                  if dim not in MARKET_DIMS or market_date is not None and _market_date(row) == market_date]
        values = [value for value in values if value is not None]
        counts[dim] = len(values)
        means[dim] = math.fsum(values) / len(values) if len(values) >= 3 else None
    ranked = [row for row in bucket if _composite(row) is not None
              and market_date is not None and _market_date(row) == market_date]
    ranked.sort(key=lambda row: (-_composite(row), row['code']))
    own = _composite(target)
    rank = (1 + sum(_composite(row) > own for row in ranked)
            if own is not None and len(ranked) >= 3 and any(row['code'] == target['code'] for row in ranked)
            else None)
    return dict(name=name, bucket=bucket, ranked=ranked, rank=rank, means=means, counts=counts)


def peer_context(snapshot, code):
    target = next((row for row in _rows(snapshot) if row['code'] == code), None)
    if target is None:
        return None
    context = _context(snapshot, target)
    return context['name'], len(context['ranked']), context['rank'], context['means']


def _details(target):
    rows = []
    for dim in DIMS:
        detail = _dimension(target, dim)
        status = STATUS.get(detail.get('status'), '缺失')
        metrics = detail.get('metrics', [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            key = str(metric.get('key', ''))
            value = _number(metric.get('value'))
            contribution = '未计分'
            if _score(target, dim) is not None:
                delta = _number(metric.get('delta'))
                weighted = _number(metric.get('contribution'))
                if delta is not None:
                    contribution = f'{delta:+g}分'
                elif weighted is not None:
                    weight, component = _number(metric.get('weight')), _number(metric.get('score'))
                    contribution = (f'{component:g} × {weight:.0%} = {weighted:g}分'
                                    if weight is not None and component is not None else f'{weighted:g}分')
            rows.append([detail.get('label', dim), status, METRIC_LABELS.get(key, key),
                         value if value is not None else '缺失', str(metric.get('unit', '')),
                         str(metric.get('rule', '')), contribution])
    return rows


def snapshot_view(snapshot, code):
    rows = _rows(snapshot)
    target = next((row for row in rows if row['code'] == str(code)), None)
    if target is None:
        return None, '未找到同版本、同批次和同期间的有效评分快照。', '', []
    context = _context(snapshot, target)
    values = [_score(target, dim) for dim in DIMS]
    count = sum(value is not None for value in values)
    name = escape(target['stock_name'])
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=values + values[:1], theta=DIMS + DIMS[:1],
        mode='lines+markers', name=name, connectgaps=False,
        line=dict(color=C['blue'], width=2), marker=dict(size=5),
        fill='toself' if count == 5 else 'none', fillcolor='rgba(37,99,235,0.15)',
        hovertemplate='%{theta}：%{r:.1f}<extra></extra>'))
    mean_values = [context['means'][dim] for dim in DIMS]
    samples = [context['counts'][dim] for dim in DIMS]
    fig.add_trace(go.Scatterpolar(r=mean_values + mean_values[:1], theta=DIMS + DIMS[:1],
        customdata=samples + samples[:1], mode='lines+markers', connectgaps=False,
        name=f"{escape(context['name'])}均值", line=dict(color=C['amber'], width=1.6, dash='dash'),
        fill='none', hovertemplate='%{theta}均值：%{r:.1f}<br>有效样本 n=%{customdata}<extra></extra>'))
    fig.update_layout(template='plotly_white', font=dict(family='Microsoft YaHei, sans-serif', color=C['dark'], size=12),
        title=dict(text=f'{name} 五维观察', font=dict(size=15)), paper_bgcolor='white',
        legend=dict(orientation='h', y=-.12, x=0), margin=dict(l=50, r=50, t=55, b=60),
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor=C['grid']),
                   angularaxis=dict(categoryorder='array', categoryarray=DIMS, gridcolor=C['grid'], rotation=90, direction='clockwise')))
    if count == 0:
        fig.add_annotation(text='该公司五维均无可用评分', showarrow=False, x=.5, y=.5, xref='paper', yref='paper')
    composite = _composite(target)
    composite_text = f'{composite:.1f}' if composite is not None else '缺项' if count < 5 else '不可用'
    notes = (f"**{name}（{escape(target['code'])}）** · 有效维度 {count}/5 · 综合分：{composite_text}\n\n"
             f"市场日期：{escape(_market_date(target) or '缺失')}；"
             f"财务报告期：{escape(snapshot['financial_period'])}。\n\n")
    if context['rank'] is None:
        notes += '不参与综合排名：存在缺项、综合记录无效或同日期完整可比样本不足3家。\n\n'
    else:
        notes += f"{escape(context['name'])}综合排名 {context['rank']} / {len(context['ranked'])}，同分并列。\n\n"
    notes += ('<details><summary>评分口径与可比样本</summary>\n\n'
              f"截至日期：{escape(snapshot['as_of'])}；批次：{escape(snapshot['batch_id'])}；版本：{VERSION}。\n\n"
              f"可比组 {len(context['bucket'])} 家；完整且市场日期一致 {len(context['ranked'])} 家；"
              f"排除缺项、综合记录无效或市场日期不同 {len(context['bucket']) - len(context['ranked'])} 家；"
              f"快照中过期、跨版本、批次/期间不一致或重复记录剔除 {len(snapshot['rows']) - len(rows)} 条。\n\n"
              '维度均值至少需要3份有效观测；市场三维还要求市场日期一致。'
              '阈值为研究假设，非经验证评级；正PE分档不表示周期行业便宜。\n\n</details>')
    rank_html = ''
    if context['rank'] is not None:
        rank_html = format_peer_ranking(context['name'], [(row['stock_name'], _composite(row)) for row in context['ranked']], context['rank'])
    return fig, notes, rank_html, _details(target)


def _resolve(snapshot, query):
    q = str(query).strip().lower()
    if not q:
        return None
    rows = _rows(snapshot)
    exact = [row for row in rows if q in (row['code'].lower(), row['stock_name'].lower(), row['code'].lower().split('.')[-1])]
    matches = exact or [row for row in rows if q in row['code'].lower() or q in row['stock_name'].lower()]
    return matches[0] if len(matches) == 1 else None


def query_view(query, snapshot=None):
    snapshot = read_snapshot() if snapshot is None else snapshot
    if not _header(snapshot):
        return None, '暂无2.0评分快照，请先完成同批次采集；旧版评分不自动迁移。', '', []
    target = _resolve(snapshot, query)
    if target is None:
        return None, '未找到唯一有效公司，请提供完整名称或股票代码。', '', []
    return snapshot_view(snapshot, target['code'])


def _source_text(value):
    if value is None:
        return '未记录'
    if isinstance(value, bool):
        return '是' if value else '否'
    return escape(str(value)).replace('\n', ' ')


def _source_link(url):
    if not isinstance(url, str) or any(ord(char) < 32 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return None
    except ValueError:
        return None
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(parsed.hostname)}</a>'


def _source_lines(value, depth=0):
    """Render structured provenance without dumping serialized JSON into the UI."""
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            label = _source_text(SOURCE_LABELS.get(key, key))
            if isinstance(item, (dict, list)):
                lines.append(f'<details><summary>{label}（{len(item)}项）</summary>\n\n')
                lines.extend(_source_lines(item, depth + 1))
                lines.append('\n</details>\n')
            else:
                lines.append(f'- {label}：{_source_link(item) or _source_text(item)}')
        return lines
    if isinstance(value, list):
        lines = []
        for index, item in enumerate(value, 1):
            if isinstance(item, (dict, list)):
                lines.append(f'<details><summary>记录 {index}</summary>\n\n')
                lines.extend(_source_lines(item, depth + 1))
                lines.append('\n</details>\n')
            else:
                lines.append(f'- {_source_text(item)}')
        return lines
    return [_source_text(value)]


def _issue_text(issue):
    key, _, reason = str(issue).partition(':')
    label = SOURCE_LABELS.get(key, {'quote': '估值行情', 'market': '市场数据',
        'financial_online': '财务在线来源', 'financial_local': '财务本地来源'}.get(key, key))
    translations = {
        'specified period with known announcement <= as_of unavailable': '找不到指定报告期、且公告日在截止日之前的记录',
        'missing comparable parent net profit or nonpositive prior-year base': '缺少可比归母净利润，或上年同期利润不为正',
        'legacy cached period cannot be verified against same-period weighted ROE': '缓存ROE无法通过同报告期加权ROE核验',
        'same-period verification unavailable': '同报告期核验暂不可用',
        'source field missing': '来源字段缺失',
        'quote trading date does not match technical market_date': '估值行情日期与技术指标市场日期不同',
        'stale >4 calendar days; market metrics withheld': '行情超过4个自然日，市场指标已留空',
    }
    clean = reason.strip()
    return f'{_source_text(label)}：{_source_text(translations.get(clean, clean or issue))}'


def quality_note(query, snapshot=None):
    snapshot = read_snapshot() if snapshot is None else snapshot
    target = _resolve(snapshot, query)
    if target is None:
        return '暂无该公司的有效来源记录。披露质量单独展示，不计入经营风险分。'
    lines = [f"**{escape(target['stock_name'])} · 来源与数据状态**",
             f"批次：{escape(snapshot['batch_id'])}；财务报告期：{escape(snapshot['financial_period'])}；市场日期：{escape(_market_date(target) or '缺失')}。"]
    raw = target['raw']
    lines.append('### 来源日期\n')
    dates = raw.get('source_dates')
    lines.extend(_source_lines(dates) if dates else ['未记录来源日期。'])
    lines.append('### 来源链接\n')
    urls = raw.get('source_urls')
    links = [f"- {_source_text(SOURCE_LABELS.get(key, key))}：{_source_link(url) or '链接不可用'}"
             for key, url in urls.items()] if isinstance(urls, dict) else []
    lines.extend(links or ['未记录可访问的来源链接。'])
    lines.append('### 来源详情\n')
    details = raw.get('source_details')
    lines.extend(_source_lines(details) if details else ['未记录来源详情。'])
    lines.append('### 缺项与数据问题\n')
    missing = [METRIC_LABELS.get(key, key) for dim in DIMS for key in _dimension(target, dim).get('missing', [])]
    if missing:
        lines.append('缺失指标：' + '、'.join(dict.fromkeys(missing)) + '。')
    issues = raw.get('issues')
    lines.extend(['- ' + _issue_text(issue) for issue in issues] if isinstance(issues, list) and issues
                 else ['未记录问题（不代表已验证完整）。'])
    lines.append('披露质量与来源校验状态单独展示，不混入安全度扣分；评分不能替代原始资料核验。')
    return '\n\n'.join(lines)
