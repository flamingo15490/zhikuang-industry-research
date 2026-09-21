"""Independent score inspection from persisted observations."""
import gradio as gr

from score_view import query_view, quality_note, read_snapshot


def requested_score(value):
    snapshot = read_snapshot()
    # An empty explicit snapshot prevents a second read after a failed load.
    snapshot = snapshot if snapshot is not None else {}
    figure, note, ranking, details = query_view(value, snapshot=snapshot)
    return {'query': value, 'view': (note, figure, ranking, details,
                                   quality_note(value, snapshot=snapshot))}


def commit_score(candidate, value):
    if not candidate or candidate['query'] != value:
        return (gr.skip(),) * 5
    return candidate['view']


def build_score_panel():
    candidate = gr.State(None)
    with gr.Column(elem_id='score_workspace'):
        with gr.Row():
            query = gr.Textbox(label='评分公司', value='紫金矿业', placeholder='完整名称或代码')
            button = gr.Button('查看评分快照', variant='primary')
        meta = gr.Markdown(elem_id='score_meta')
        chart = gr.Plot(show_label=False, elem_id='score_radar')
        rank = gr.HTML(elem_id='score_rank')
        with gr.Accordion('五维分别评什么', open=False):
            gr.Markdown('''五维完整时，各占综合分的 **20%**；缺项或不适用时不计算综合分。

| 维度 | 观察的问题 | 计算依据 |
| --- | --- | --- |
| 基本面 | 盈利能力和利润变化如何 | 净资产收益率分档分占70%，净利润增长分档分占30% |
| 估值观察 | 股价相对最近一年盈利处在什么水平 | 正市盈率分档；亏损或零盈利不适用 |
| 技术面 | 近期价格趋势如何 | 从50分起，根据均线、MACD、RSI和20日涨跌加减分 |
| 资金面 | 资金净流入相对交易规模有多大 | 同五日净流入÷成交额，按比例计分 |
| 安全度 | 财务杠杆、偿债能力和利润变化如何 | 资产负债率40%，增长30%，流动比率30% |

增长在基本面和安全度中重复使用，合计占综合分的12%。这些阈值是研究规则，尚未经过收益预测验证；高分不等于更值得买入。''')
        with gr.Accordion('各维指标与计分明细', open=True):
            table = gr.Dataframe(headers=['维度', '状态', '指标', '原始值', '单位', '规则', '计分贡献'],
                                 interactive=False, wrap=True, elem_id='score_details')
        with gr.Accordion('数据日期与缺项', open=False):
            quality = gr.Markdown(elem_id='score_quality')

    outputs = [meta, chart, rank, table, quality]
    button.click(requested_score, inputs=query, outputs=candidate).then(
        commit_score, inputs=[candidate, query], outputs=outputs)
    query.submit(requested_score, inputs=query, outputs=candidate).then(
        commit_score, inputs=[candidate, query], outputs=outputs)
    query.change(lambda: ('尚未加载该公司的评分', None, '', [], '', None), outputs=[*outputs, candidate], queue=False)
    return {'query': query, 'candidate': candidate, 'outputs': outputs}
