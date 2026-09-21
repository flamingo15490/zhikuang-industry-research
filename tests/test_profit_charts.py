import pytest


def test_bridge_keeps_signed_totals_and_uses_horizontal_layout():
    from profit_charts import draw_profit_bridge
    result = {
        'name': '亏损样本', 'period': '2026-06-30', 'bridge_status': 'complete',
        'bridge': {'labels': ['营业收入', '营业成本', '毛利', '所得税', '归母净利润'],
                   'values': [10, -12, -2, 0.5, -1.5],
                   'measures': ['absolute', 'relative', 'total', 'relative', 'total'],
                   'origins': ['reported'] * 5, 'units': '亿元'},
    }
    fig = draw_profit_bridge(result)
    trace = fig.data[0]
    assert trace.orientation == 'h'
    assert list(trace.x) == [10, -12, 0, 0.5, 0]
    assert trace.customdata[-1][0] == -1.5
    assert '2026-06-30' in fig.layout.title.text


def test_segment_chart_excludes_unknown_or_inconsistent_profit():
    from profit_charts import draw_segment_profit
    result = {'name': '测试', 'segment_period': '2026-06-30', 'segments': [
        {'name': '业务 A', 'gross_profit': -1e8, 'revenue': 2e8, 'margin': -0.5,
         'excluded': False, 'status': 'valid'},
        {'name': '业务 B', 'gross_profit': None, 'excluded': False, 'status': 'missing'},
        {'name': '异常', 'gross_profit': 9e8, 'excluded': True, 'status': 'inconsistent'},
    ]}
    fig = draw_segment_profit(result)
    assert list(fig.data[0].x) == [-1]
    assert list(fig.data[0].y) == ['业务 A']


def test_missing_bridge_is_an_explicit_empty_state():
    from profit_charts import draw_profit_bridge
    fig = draw_profit_bridge({'name': '测试', 'bridge': {}, 'bridge_status': 'missing'})
    assert not fig.data
    assert '数据' in fig.layout.annotations[0].text


def test_disclosed_unit_margin_preserves_original_units_and_loss():
    from profit_charts import draw_disclosed_unit_margin
    product = {'name': '冶炼锌', 'price': 100, 'cost': 110, 'gross_margin': -10,
               'unit': '元/吨', 'scope': '抵销前', 'source_url': 'https://example.com/report'}
    fig = draw_disclosed_unit_margin('测试', '2026-06-30', product)
    assert list(fig.data[0].x) == [100, -110, 0]
    assert fig.data[0].customdata[-1][0] == -10
    assert fig.layout.xaxis.title.text == '元/吨'
