"""Profit charts render validated financial data; calculations live in tools."""
from __future__ import annotations

from html import escape
import math

import plotly.graph_objects as go
from ui_glossary import chart_explanation

BLUE, RED, GREEN, GRAY = '#2563eb', '#dc4660', '#16836b', '#64748b'


def _layout(title: str, height: int = 500) -> dict:
    return dict(
        template='plotly_white', height=height,
        title=dict(text=title, font=dict(size=14), x=0.02),
        font=dict(family='Microsoft YaHei, sans-serif', size=12, color='#334155'),
        margin=dict(l=112, r=28, t=65, b=50), paper_bgcolor='white',
        plot_bgcolor='white', showlegend=False,
        uniformtext=dict(minsize=11, mode='hide'),
        hoverlabel=dict(bgcolor='white', font_size=13),
        xaxis=dict(gridcolor='#e2e8f0', zerolinecolor='#94a3b8', automargin=True),
        yaxis=dict(autorange='reversed', automargin=True),
    )


def empty_profit_chart(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=escape(message), showarrow=False, font=dict(size=13, color=GRAY))
    fig.update_layout(template='plotly_white', height=230, margin=dict(l=15, r=15, t=15, b=15),
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _label(value: str) -> str:
    text = str(value)
    return '<br>'.join(escape(text[i:i + 9]) for i in range(0, len(text), 9))


def _waterfall(labels, values, measures, origins, title, unit, height=550, provenance=None):
    # Plotly total bars calculate their own height; keep reported totals in hover data.
    plotted = [0 if measure == 'total' else value for value, measure in zip(values, measures)]
    fig = go.Figure(go.Waterfall(
        orientation='h', y=[_label(label) for label in labels], x=plotted,
        measure=measures, text=[f'{value:+,.2f}' for value in values], textposition='inside',
        constraintext='inside', textangle=0,
        customdata=[[value, origin, *(provenance or ['', '', '']), chart_explanation(label)]
                    for value, origin, label in zip(values, origins, labels)],
        connector=dict(line=dict(color='#cbd5e1', width=1)),
        increasing=dict(marker=dict(color=BLUE)), decreasing=dict(marker=dict(color=RED)),
        totals=dict(marker=dict(color=GREEN)),
        hovertemplate=f'%{{y}}<br>%{{customdata[0]:,.4f}} {escape(unit)}'
                      '<br>%{customdata[1]}'
                      + ('<br>报告期 %{customdata[2]}<br>公告日 %{customdata[3]}<br>%{customdata[4]}' if provenance else '')
                      + '%{customdata[5]}<extra></extra>',
    ))
    fig.update_layout(**_layout(title, height))
    fig.update_xaxes(title=unit)
    return fig


def draw_profit_bridge(analysis: dict) -> go.Figure:
    bridge = analysis.get('bridge') or {}
    labels = bridge.get('labels') or []
    if not labels:
        return empty_profit_chart('缺少可核验的利润表数据')
    origins = {'reported': '财报披露', 'derived': '报表数值推导', 'reconciliation': '未细分损益差额'}
    return _waterfall(
        labels, bridge['values'], bridge['measures'],
        [origins.get(value, value) for value in bridge['origins']],
        f"{escape(analysis['name'])} · 财报利润桥<br><sup>{analysis.get('period', '')} · 财报实绩</sup>",
        bridge.get('units', '亿元'), max(420, len(labels) * 34 + 100),
        [analysis.get('period') or '未知', analysis.get('notice_date') or '未提供', '来源：东方财富财报数据'],
    )


def draw_segment_profit(analysis: dict) -> go.Figure:
    rows = [row for row in analysis.get('segments', [])
            if not row.get('excluded') and row.get('gross_profit') is not None]
    if not rows:
        return empty_profit_chart('该报告期无可核验的分部毛利数据')
    rows = sorted(rows, key=lambda row: row['gross_profit'], reverse=True)
    values = [row['gross_profit'] / 1e8 for row in rows]
    fig = go.Figure(go.Bar(
        orientation='h', y=[_label(row['name']) for row in rows], x=values,
        marker_color=[GREEN if value >= 0 else RED for value in values],
        text=[f'{value:,.2f}' for value in values], textposition='inside',
        constraintext='inside', textangle=0,
        customdata=[[row.get('revenue', 0) / 1e8 if row.get('revenue') is not None else None,
                     f"{row['margin']:.2%}" if row.get('margin') is not None else '未披露'] for row in rows],
        hovertemplate='%{y}<br>毛利 %{x:,.4f} 亿元<br>收入 %{customdata[0]:,.4f} 亿元'
                      '<br>毛利率 %{customdata[1]}<extra></extra>',
    ))
    fig.update_layout(**_layout(
        f"{escape(analysis['name'])} · 分部毛利<br><sup>{analysis.get('segment_period') or '期间未知'} · 已披露业务</sup>",
        max(360, len(rows) * 45 + 100),
    ))
    fig.update_xaxes(title='毛利（亿元）')
    return fig


def draw_scenario_result(result: dict) -> go.Figure:
    values = list(result['values'])
    values[-1] = result['total']
    return _waterfall(result['labels'], values, result['measures'], ['假设测算'] * len(values),
                      f"{escape(result['label'])}<br><sup>假设测算 · 非公司归母净利润</sup>",
                      result['unit'], max(380, len(values) * 45 + 100))


def draw_disclosed_unit_margin(name: str, period: str, product: dict) -> go.Figure:
    return _waterfall(
        ['销售单价', '披露单位销售成本', '单位毛利（差额）'],
        [product['price'], -product['cost'], product['gross_margin']],
        ['absolute', 'relative', 'total'], ['公告披露', '公告披露', '同口径售价减成本'],
        f"{escape(name)} · {escape(product['name'])}<br><sup>{period} · 已披露单位经济性</sup>",
        product['unit'], 320,
    )


def draw_scenario_heatmap(model: str, values: dict) -> go.Figure:
    from tools.profit_scenarios import MODELS, calculate_scenario

    config = MODELS[model]
    xkey, ykey = config['axes']
    fields = {field['key']: field for field in config['fields']}

    def scale(key):
        value = float(values[key])
        if value == 0:
            return None
        lo, hi = sorted([value * 0.7, value * 1.3])
        return [lo + (hi - lo) * i / 20 for i in range(21)]

    xs, ys = scale(xkey), scale(ykey)
    if xs is None or ys is None:
        return empty_profit_chart('敏感性轴的基准值为零，暂无可用变化区间')
    z = []
    for y in ys:
        row = []
        for x in xs:
            scenario = dict(values, **{xkey: x, ykey: y})
            try:
                row.append(calculate_scenario(model, scenario)['total'])
            except ValueError:
                row.append(None)
        z.append(row)
    finite = [v for row in z for v in row if v is not None and math.isfinite(v)]
    if not finite:
        return empty_profit_chart('当前参数范围内没有有效情景')
    fig = go.Figure(go.Heatmap(
        x=xs, y=ys, z=z, zmid=0,
        colorscale=[[0, '#c63d55'], [0.5, '#f8fafc'], [1, '#16836b']],
        colorbar=dict(title='利润', thickness=12),
        hovertemplate=f"{escape(fields[xkey]['label'])} %{{x:,.2f}}<br>"
                      f"{escape(fields[ykey]['label'])} %{{y:,.2f}}<br>"
                      f"利润 %{{z:,.2f}} {escape(config['unit'])}<extra></extra>",
    ))
    if min(finite) < 0 < max(finite):
        fig.add_trace(go.Contour(x=xs, y=ys, z=z, showscale=False, hoverinfo='skip',
                                contours=dict(start=0, end=0, size=1, coloring='none', showlabels=True),
                                line=dict(color='#334155', width=2), name='盈亏平衡'))
    fig.add_trace(go.Scatter(x=[values[xkey]], y=[values[ykey]], mode='markers',
                            marker=dict(symbol='cross', size=10, color='#111827'),
                            name='输入基准', hovertemplate='输入基准<extra></extra>'))
    fig.update_layout(**_layout('双因素敏感性<br><sup>输入基准上下浮动 30% · 其余参数不变</sup>', 420))
    fig.update_layout(margin=dict(l=70, r=30, t=70, b=75))
    fig.update_xaxes(title=f"{fields[xkey]['label']}（{fields[xkey]['unit']}）")
    fig.update_yaxes(title=f"{fields[ykey]['label']}（{fields[ykey]['unit']}）", autorange=True)
    return fig
