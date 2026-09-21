"""Traceable financial evidence and allowlisted local research exports."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import uuid4

BASE = Path(__file__).resolve().parent
LABELS = {'OPERATE_INCOME': '营业收入', 'OPERATE_COST': '营业成本', 'GROSS_PROFIT': '毛利',
          'OPERATE_PROFIT': '营业利润', 'TOTAL_PROFIT': '利润总额', 'NETPROFIT': '净利润',
          'PARENT_NETPROFIT': '归母净利润', 'INCOME_TAX': '所得税', 'MINORITY_INTEREST': '少数股东损益'}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _url(value):
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or parts.username or parts.password:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query) if not any(s in k.lower() for s in ('token', 'key', 'auth', 'secret'))]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def build_evidence(analysis: dict) -> list[dict]:
    from tools.operating_disclosure import disclosure_for_analysis
    from tools.profit_analysis import DETAILS
    code, period = analysis.get('code'), analysis.get('period')
    if not code or not period:
        return []
    records = []
    labels = {**LABELS, **{keys[0]: label for label, keys, _ in DETAILS},
              'ASSET_IMPAIRMENT_LOSS': '资产减值损失（旧口径）',
              'CREDIT_IMPAIRMENT_LOSS': '信用减值损失（旧口径）'}
    source = analysis.get('source') or {}
    def add(key, metric, value, unit='元', *, kind='reported', formula=None, inputs=(),
            report_period=period, notice=analysis.get('notice_date'), url=source.get('url'),
            limitations=(), scope='合并利润表', page=None):
        if not _finite(value):
            return None
        identity = f'{code}|{report_period}|{key}|{scope}'
        eid = 'E-' + sha256(identity.encode()).hexdigest()[:12]
        records.append(dict(evidence_id=eid, metric=metric, value=value, unit=unit,
                            period=report_period, notice_date=notice, source_url=_url(url),
                            source_kind=kind, formula=formula, input_ids=list(inputs),
                            limitations=list(limitations), scope=scope, page=page))
        return eid
    statement = analysis.get('statement') or {}
    ids = {}
    # Full source tables also contain EPS, growth rates and numeric metadata.
    for key in sorted(labels.keys() & statement.keys()):
        if key == 'GROSS_PROFIT':
            continue
        eid = add(key, labels[key], statement[key], limitations=['第三方财报转录；不是原报告逐页核验。'])
        if eid:
            ids[key] = eid
    if all(key in ids for key in ('OPERATE_INCOME', 'OPERATE_COST')):
        add('GROSS_PROFIT', '毛利', statement['OPERATE_INCOME'] - statement['OPERATE_COST'],
            kind='derived', formula='营业收入 - 营业成本',
            inputs=[ids['OPERATE_INCOME'], ids['OPERATE_COST']])
    segment_source = analysis.get('segment_source') or {}
    for index, row in enumerate(analysis.get('segments') or []):
        limits = ['分部公告时点未核实。', row.get('reason') or '',
                  '未纳入合并加总。' if row.get('excluded') else '分部毛利不等于公司净利润。']
        segment_ids = []
        for key, label in [('revenue', '收入'), ('cost', '成本')]:
            eid = add(f'segment-{index}-{key}', f"{row['name']}：{label}", row.get(key),
                      report_period=analysis.get('segment_period'), notice=None,
                      url=segment_source.get('url'), scope=row['name'], limitations=limits)
            if eid:
                segment_ids.append(eid)
        if len(segment_ids) == 2:
            add(f'segment-{index}-gross', f"{row['name']}：毛利", row['revenue'] - row['cost'],
                kind='derived', formula='分部收入 - 分部成本', inputs=segment_ids,
                report_period=analysis.get('segment_period'), notice=None,
                url=segment_source.get('url'), scope=row['name'], limitations=limits)
    disclosure = disclosure_for_analysis(analysis)
    for index, product in enumerate(disclosure['products']):
        unit_ids = []
        limits = ['正式公告文本已核对，PDF版式未核验。', '综合成本不可与运输、折旧等重复扣除。']
        for key, label in [('price', '销售单价'), ('cost', '单位销售成本')]:
            unit_ids.append(add(f'product-{index}-{key}', f"{product['name']}：{label}", product[key],
                                product['unit'], scope=product['scope'], url=product['source_url'],
                                page=product.get(f'{key}_page'), notice=None,
                                limitations=limits, kind='announcement_text_checked'))
        add(f'product-{index}-margin', f"{product['name']}：单位毛利", product['gross_margin'], product['unit'],
            scope=product['scope'], url=product['source_url'], notice=None, kind='derived',
            formula='同口径售价 - 单位销售成本', inputs=unit_ids, limitations=limits + ['不等于归母净利润。'])
    return records


def evidence_html(records):
    if not records:
        return '<p>尚无可追溯的财报证据。</p>'
    rows = []
    for item in records:
        source = _url(item.get('source_url'))
        link = f'<a href="{escape(source, quote=True)}" target="_blank" rel="noopener noreferrer">数据来源</a>' if source else '未提供原始链接'
        formula = f"推导：{item['formula']}；输入：{', '.join(item['input_ids'])}" if item['formula'] else '披露记录'
        rows.append(f'<details><summary>{escape(item["metric"])} · {item["value"]:,.4f} {escape(item["unit"])}</summary>'
                    f'<p>编号 {item["evidence_id"]} · {escape(str(item["period"]))} · 公告日 {escape(str(item["notice_date"] or "未核实"))}</p>'
                    f'<p>{escape(formula)} · {link}</p><p>{escape(item["scope"])}</p>'
                    f'<p>{escape("；".join(filter(None, item["limitations"])))}</p></details>')
    return '<div class="evidence-list">' + ''.join(rows) + '</div>'


def evidence_summary(records):
    keys = {'营业收入', '营业成本', '毛利', '归母净利润'}
    return '\n'.join(f"[{r['evidence_id']}] {r['metric']}={r['value']} {r['unit']}；期间{r['period']}；{r['source_kind']}"
                     for r in records if r['metric'] in keys)


def save_research_run(run: dict, output_dir: Path) -> Path:
    analysis = run['analysis']
    records = build_evidence(analysis)
    if not records:
        raise ValueError('尚无可导出的财报证据')
    folder = Path(output_dir) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    paths = [BASE / 'prompts.py', BASE / 'report.py', BASE / 'research_evidence.py',
             BASE / 'tools/profit_analysis.py', BASE / 'tools/operating_disclosure.py',
             BASE / 'data/profit_analysis/operating_metrics.json']
    for src in ('source', 'segment_source'):
        value = (analysis.get(src) or {}).get('path')
        if value:
            path = Path(value).resolve()
            if path.is_relative_to(BASE / 'data'):
                paths.append(path)
    fingerprints = {str(p.relative_to(BASE)): sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    snapshot = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
                    code=analysis['code'], name=analysis['name'], period=analysis['period'],
                    model=run.get('model') or '未调用LLM（确定性财报快照）',
                    prompt_sha256=sha256(str(run.get('prompt', '')).encode()).hexdigest(),
                    fingerprints=fingerprints, evidence=records,
                    limitations=['确定性快照可复核；不保证LLM措辞逐字复现。', *analysis.get('warnings', [])])
    (folder / 'evidence.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = [f"# {analysis['name']} 研究证据快照", f"报告期：{analysis['period']}",
             '以下为确定性披露与推导记录；不是完整投研建议。', evidence_summary(records),
             '| 证据编号 | 项目 | 金额 | 单位 | 期间 | 依据 |', '|---|---|---:|---|---|---|']
    for r in records:
        clean = lambda v: str(v or '').replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {r['evidence_id']} | {clean(r['metric'])} | {r['value']:,.4f} | {clean(r['unit'])} | {r['period']} | {clean(r['source_kind'])} |")
    lines += ['\n## 数据限制', *['- ' + text for text in snapshot['limitations']]]
    (folder / 'report.md').write_text('\n\n'.join(lines[:4]) + '\n\n' + '\n'.join(lines[4:]), encoding='utf-8')
    return folder
