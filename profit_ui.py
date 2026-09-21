"""Valuation workspace for reported profits and explicit operating scenarios."""
from __future__ import annotations

from html import escape
from hashlib import sha256
import json
import math

import gradio as gr
from ui_glossary import help_heading
from research_evidence import build_evidence, evidence_html, save_research_run, BASE

from profit_charts import (draw_profit_bridge, draw_segment_profit,
                           draw_scenario_heatmap, draw_scenario_result, draw_disclosed_unit_margin)


def _amount(value, scale=1e8):
    return None if value is None else round(float(value) / scale, 4)


def financial_overview(data):
    statement = data.get('statement') or {}
    def display(key):
        value = statement.get(key)
        if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
            return '未披露'
        return f'{float(value) / 1e8:,.2f}'
    return ('\n\n| 营业收入 | 毛利 | 归母净利润 |\n| ---: | ---: | ---: |\n'
            f"| {display('OPERATE_INCOME')} | {display('GROSS_PROFIT')} | {display('PARENT_NETPROFIT')} |\n\n"
            '金额单位：亿元；采用上方报告期累计值，毛利由收入减成本计算。')


def load_profit(query: str, period: str | None = None) -> dict | None:
    from tools.profit_analysis import analyze_profit
    if not query or not query.strip():
        return None
    try:
        return analyze_profit(query.strip(), period=period)
    except (ValueError, FileNotFoundError, KeyError, OSError) as error:
        return {'error': str(error)}


def requested_profit(query, selection=None, use_selected=False):
    result = load_profit(query, selection if use_selected else None)
    if result is not None:
        result['_request_query'] = query
        result['_selection'] = selection
        result['_use_selected'] = use_selected
    return result


def commit_profit(candidate, query, selection, current):
    # A sync fetch may finish after the user has changed company or period.
    if candidate is None:
        return None if not query else current
    if candidate.get('_request_query') != query:
        return current
    if candidate.get('_use_selected', True) and candidate.get('_selection') != selection:
        return current
    return candidate


def financial_view(data: dict | None):
    from tools.profit_scenarios import MODELS
    if not data or data.get('error') or not data.get('name'):
        message = escape(data.get('error') or data.get('summary') or '尚未加载公司利润数据') if data else '尚未加载公司利润数据'
        return (gr.update(choices=[], value=None), message, None, [], '', None, [],
                gr.update(value=None))
    source = data.get('source') or {}
    source_name = '完整利润表' if source.get('kind') == 'complete' else '历史财报缓存'
    business = ' / '.join(MODELS[key]['label'] for key in data.get('business_types', []) if key in MODELS)
    status = {'complete': '勾稽通过', 'partial': '部分披露', 'missing': '数据不足',
              'inconsistent': '存在勾稽差异'}.get(data.get('bridge_status'), '待核验')
    meta = (f"**{escape(data['name'])} · {data['code']}**　{escape(business or '经营环节尚未确认')}\n\n"
            f"报告期 {data.get('period') or '未知'}　·　公告日 {data.get('notice_date') or '未提供'}"
            f"　·　{source_name}　·　{status}")
    if source.get('url'):
        meta += f"　·　[数据来源]({source['url']})"
    meta += financial_overview(data)
    warnings = list(dict.fromkeys(data.get('warnings') or []))
    if warnings:
        meta += '\n\n' + '\n\n'.join('> ' + escape(str(warning)) for warning in warnings)
    bridge = data.get('bridge') or {}
    origin_names = {'reported': '披露', 'derived': '推导', 'reconciliation': '未细分差额'}
    bridge_rows = [[label, round(value, 4), origin_names.get(origin, origin)]
                   for label, value, origin in zip(bridge.get('labels', []), bridge.get('values', []),
                                                   bridge.get('origins', []))]
    segment_rows = [[row['name'], _amount(row.get('revenue')), _amount(row.get('cost')),
                     _amount(row.get('gross_profit')),
                     round(row['margin'] * 100, 2) if row.get('margin') is not None else None,
                     row.get('reason') or ('未纳入加总' if row.get('excluded') else '已披露')]
                    for row in data.get('segments', [])]
    segment_status = {'verified': '与公司报表同口径核验通过', 'comparison_only': '仅比较已披露分部，不作公司利润加总',
                      'period_mismatch': '与公司利润桥期间不同，不作跨期贡献率计算',
                      'missing': '该期间无可用分部披露'}.get(data.get('segment_status'), '按原始披露展示')
    segment_note = f"**分部报告期 {data.get('segment_period') or '未知'}**　·　{segment_status}"
    valid_models = [key for key in data.get('business_types', []) if key in MODELS]
    return (gr.update(choices=data.get('periods') or [], value=data.get('period')), meta,
            draw_profit_bridge(data), bridge_rows, segment_note, draw_segment_profit(data), segment_rows,
            gr.update(value=valid_models[0] if valid_models else None))


def _scenario_config(model):
    from tools.profit_scenarios import MODELS, scenario_defaults
    maximum = max(len(item['fields']) for item in MODELS.values())
    if not model or model not in MODELS:
        return ('', *[gr.Number(visible=False, value=None, minimum=None, maximum=None, render=False) for _ in range(maximum)],
                '尚未选择经营情景', None, None)
    config, defaults = MODELS[model], scenario_defaults(model)
    fields = []
    for index in range(maximum):
        if index >= len(config['fields']):
            fields.append(gr.Number(value=None, visible=False, minimum=None, maximum=None, render=False))
            continue
        field = config['fields'][index]
        key = field['key']
        source = defaults.get('sources', {}).get(key) or '尚无可核验数据'
        # Component updates retain explicit None bounds; gr.update drops them.
        fields.append(gr.Number(label=f"{field['label']}（{field['unit']}）",
                                info=source, value=defaults['values'].get(key), visible=True,
                                minimum=field.get('min'), maximum=field.get('max'), render=False))
    assumptions = list(dict.fromkeys(config.get('assumptions', []) + defaults.get('assumptions', [])))
    formula = f"**{escape(config['formula'])}**\n\n" + '\n\n'.join(escape(value) for value in assumptions)
    return (formula, *fields, '假设测算 · 缺少的输入尚未估算', None, None)


def render_financial_view(data, query=None):
    if data and data.get('code') and query is not None:
        from tools._resolve import resolve_stock
        _, current_code = resolve_stock(query) if query.strip() else (None, None)
        if current_code != data['code']:
            data = None
    financial = financial_view(data)
    return (*financial, *_scenario_config(financial[-1]['value']))


def scenario_view(model: str | None, *numbers):
    from tools.profit_scenarios import MODELS, calculate_scenario
    if not model or model not in MODELS:
        return '请选择经营模型', None, None
    values = {field['key']: value for field, value in zip(MODELS[model]['fields'], numbers)}
    try:
        result = calculate_scenario(model, values)
        if not math.isfinite(result['total']):
            raise ValueError('参数计算结果不是有限数值')
        return (f"**情景经营贡献 {result['total']:,.2f} {result['unit']}**　·　非公司归母净利润",
                draw_scenario_result(result), draw_scenario_heatmap(model, result['inputs']))
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as error:
        return f"暂无法测算：{escape(str(error))}", None, None


def disclosed_product_view(data, selected):
    products = data.get('products', []) if data else []
    try:
        index = int(selected)
        product = products[index] if 0 <= index < len(products) else None
    except (TypeError, ValueError):
        product = None
    if product is None:
        return None, '当前公司、报告期未取得可配对的售价与单位成本。'
    source = product.get('source_url')
    note = (f"{escape(product['scope'])}。单位毛利仅按披露售价减单位销售成本推导，"
            '不等于公司净利润；综合单位成本不可再次叠加运输等费用。')
    if source:
        note += f" [原报告]({source})"
    note += f"　·　售价页 {product.get('price_page') or '未提供'} / 成本页 {product.get('cost_page') or '未提供'}"
    note += '\n\n公告原文文本已核对，PDF版式未核验。'
    return draw_disclosed_unit_margin(data['name'], data['period'], product), note


def disclosure_view(analysis):
    from tools.operating_disclosure import disclosure_for_analysis
    if not analysis or not analysis.get('code'):
        return None, gr.update(choices=[], value=None), '当前无已核对的经营披露。', None, []
    data = disclosure_for_analysis(analysis)
    data['name'] = analysis['name']
    choices = [(f"{row['name']} · {row['unit']} · {row['scope']}", str(index))
               for index, row in enumerate(data['products'])]
    selected = choices[0][1] if choices else None
    chart, note = disclosed_product_view(data, selected)
    rows = [[row['commodity'], row['metric'], row['value'], row['unit'], row['period'], row.get('page')]
            for row in data['records']]
    if not choices and rows:
        note = '已取得以下经营指标，尚无同口径售价与成本组合，不能计算单位毛利。'
    if data.get('warnings'):
        note += '\n\n' + '；'.join(escape(str(value)) for value in data['warnings'])
    return data, gr.update(choices=choices, value=selected), note, chart, rows


def render_workspace(data, query):
    financial = render_financial_view(data, query)
    active = data if financial[0].get('value') is not None else None
    return (*financial, *disclosure_view(active))


def evidence_for_query(data, query):
    from tools._resolve import resolve_stock
    if not data or not data.get('code') or not query or resolve_stock(query)[1] != data['code']:
        return evidence_html([]), None
    return evidence_html(build_evidence(data)), None


def _export_fingerprint(data):
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def export_evidence(data, query, selected_period):
    if (not data or not selected_period or data.get('period') != selected_period
            or evidence_for_query(data, query)[0] == evidence_html([])):
        raise gr.Error('请先加载当前公司、所选报告期的利润数据。')
    fingerprint = _export_fingerprint(data)
    folder = save_research_run({'analysis':data}, BASE / 'output/research_runs')
    return {'query': query, 'period': selected_period, 'fingerprint': fingerprint,
            'files': [str(folder / 'report.md'), str(folder / 'evidence.json')]}


def commit_export(candidate, query, selected_period, data):
    # File writing can finish after navigation or a refreshed snapshot arrives.
    if (not candidate or not data or candidate['query'] != query
            or candidate['period'] != selected_period or data.get('period') != selected_period
            or candidate['fingerprint'] != _export_fingerprint(data)):
        return None
    return candidate['files']


def build_profit_panel(stock_input):
    from tools.profit_scenarios import MODELS
    state = gr.State(None)
    candidate = gr.State(None)
    export_candidate = gr.State(None)
    disclosure = gr.State(None)
    with gr.Column(elem_id='profit_workspace'):
        with gr.Row():
            period = gr.Dropdown(choices=[], value=None, label='财报报告期', min_width=180)
            load_button = gr.Button('加载利润数据', variant='secondary', min_width=150)
        meta = gr.Markdown('尚未加载公司利润数据', elem_id='profit_meta')
        with gr.Accordion('证据与导出', open=False):
            evidence_panel = gr.HTML(evidence_html([]), elem_id='research_evidence')
            export_button = gr.Button('导出财报证据快照')
            export_files = gr.File(label='简报与证据', file_count='multiple', interactive=False)
        with gr.Tabs():
            with gr.Tab('财报利润桥'):
                gr.HTML(help_heading('收入如何变成净利润', '财报利润桥'))
                bridge = gr.Plot(show_label=False, elem_id='profit_bridge_plot')
                with gr.Accordion('财报桥明细（亿元）', open=False):
                    bridge_table = gr.Dataframe(headers=['项目', '金额（亿元）', '依据'],
                                                datatype=['str', 'number', 'str'], interactive=False)
            with gr.Tab('分部毛利'):
                gr.HTML(help_heading('各项业务分别赚多少', '分部毛利'))
                segment_note = gr.Markdown()
                segments = gr.Plot(show_label=False, elem_id='profit_segment_plot')
                with gr.Accordion('分部披露明细', open=False):
                    segment_table = gr.Dataframe(
                        headers=['业务', '收入（亿元）', '成本（亿元）', '毛利（亿元）', '毛利率（%）', '数据状态'],
                        datatype=['str', 'number', 'number', 'number', 'number', 'str'], interactive=False)
            with gr.Tab('经营情景'):
                gr.HTML(help_heading('换一组价格和成本，利润会怎样', '经营情景'))
                with gr.Accordion('公司已披露经营数据', open=False):
                    product = gr.Dropdown(choices=[], value=None, label='已披露产品', elem_id='profit_product')
                    disclosure_note = gr.Markdown()
                    unit_plot = gr.Plot(show_label=False, elem_id='profit_unit_plot')
                    operating_table = gr.Dataframe(
                        headers=['产品或业务', '指标', '披露值', '单位', '报告期', '报告页码'],
                        datatype=['str', 'str', 'number', 'str', 'str', 'number'], interactive=False)
                model = gr.Dropdown(choices=[(item['label'], key) for key, item in MODELS.items()],
                                    value=None, label='经营模型', elem_id='profit_model')
                formula = gr.Markdown()
                with gr.Row():
                    with gr.Column(scale=2, min_width=250):
                        numbers = [gr.Number(value=None, visible=False, label=f'参数 {index + 1}')
                                   for index in range(max(len(item['fields']) for item in MODELS.values()))]
                        with gr.Row():
                            calculate = gr.Button('计算情景', variant='primary')
                            reset = gr.Button('恢复初始参数', variant='secondary')
                    with gr.Column(scale=3, min_width=280):
                        result_note = gr.Markdown('尚未选择经营情景')
                        scenario_plot = gr.Plot(show_label=False, elem_id='profit_scenario_plot')
                        gr.HTML(help_heading('价格与成本变化的影响', '敏感性'))
                        heatmap = gr.Plot(show_label=False, elem_id='profit_heatmap')

    scenario_outputs = [formula, *numbers, result_note, scenario_plot, heatmap]
    load_event = load_button.click(requested_profit, inputs=stock_input, outputs=candidate)
    period_event = period.input(lambda query, selected: requested_profit(query, selected, True),
                                inputs=[stock_input, period], outputs=candidate)
    load_event.then(lambda result, query, current: commit_profit(result, query, None, current),
                    inputs=[candidate, stock_input, state], outputs=state)
    period_event.then(commit_profit, inputs=[candidate, stock_input, period, state], outputs=state)
    workspace_outputs = [period, meta, bridge, bridge_table, segment_note, segments, segment_table, model,
                         *scenario_outputs, disclosure, product, disclosure_note, unit_plot, operating_table]
    state.change(render_workspace, inputs=[state, stock_input], outputs=workspace_outputs)
    state.change(evidence_for_query, inputs=[state, stock_input], outputs=[evidence_panel, export_files])
    stock_input.change(lambda: (evidence_html([]), None), outputs=[evidence_panel, export_files], queue=False)
    period.input(lambda: (evidence_html([]), None), outputs=[evidence_panel, export_files], queue=False)
    export_button.click(export_evidence, inputs=[state, stock_input, period], outputs=export_candidate).then(
        commit_export, inputs=[export_candidate, stock_input, period, state], outputs=export_files)
    product.input(disclosed_product_view, inputs=[disclosure, product], outputs=[unit_plot, disclosure_note])
    model.change(_scenario_config, inputs=model, outputs=scenario_outputs)
    reset.click(_scenario_config, inputs=model, outputs=scenario_outputs)
    calculate.click(scenario_view, inputs=[model, *numbers], outputs=[result_note, scenario_plot, heatmap])
    for number in numbers:
        number.input(lambda: ('参数已变更，尚未重新计算', None, None),
                     outputs=[result_note, scenario_plot, heatmap])
    stock_input.change(lambda query: (None, *render_workspace(None, query)), inputs=stock_input,
                       outputs=[state, *workspace_outputs])
    return state
