def test_empty_report_clears_previous_period_and_company():
    from profit_ui import financial_view
    outputs = financial_view(None)
    assert outputs[0]['choices'] == []
    assert outputs[0]['value'] is None
    assert outputs[-1]['value'] is None
    assert not outputs[3]


def test_calculation_failure_does_not_keep_previous_scenario_figures():
    from profit_ui import scenario_view
    message, figure, heatmap = scenario_view(None)
    assert '选择' in message
    assert figure is None and heatmap is None


def test_late_company_result_cannot_replace_current_company(monkeypatch):
    from profit_ui import commit_profit
    current = {'code': 'sh.600219', 'name': '南山铝业'}
    late = {'code': 'sh.601899', '_request_query': '紫金矿业', '_selection': None}
    assert commit_profit(late, '南山铝业', None, current) is current


def test_unknown_stock_renders_missing_state():
    from profit_ui import financial_view
    outputs = financial_view({'name': None, 'summary': '未找到股票'})
    assert outputs[1] == '未找到股票'
    assert outputs[2] is None


def test_same_model_financial_refresh_always_clears_scenario():
    from profit_ui import render_financial_view
    data = {'name': '测试', 'code': 'sh.600219', 'period': '2026-06-30',
            'periods': ['2026-06-30'], 'business_types': ['processing'], 'bridge': {}}
    outputs = render_financial_view(data)
    assert outputs[-2] is None and outputs[-1] is None
    assert outputs[7]['value'] == 'processing'


def test_fresh_company_load_survives_previous_period_clearing():
    from profit_ui import commit_profit
    candidate = {'_request_query': '601600', '_selection': '2026-06-30', '_use_selected': False}
    assert commit_profit(candidate, '601600', None, None) is candidate
    candidate['_use_selected'] = True
    assert commit_profit(candidate, '601600', None, None) is None


def test_disclosed_product_selection_keeps_different_scopes_separate():
    from profit_ui import disclosed_product_view
    data = {'name': '样本', 'period': '2026-06-30', 'products': [
        {'name': '铜', 'unit': '元/吨', 'scope': '抵销前', 'price': 100, 'cost': 70, 'gross_margin': 30},
        {'name': '铜', 'unit': '元/吨', 'scope': '抵销后', 'price': 100, 'cost': 90, 'gross_margin': 10},
    ]}
    figure, note = disclosed_product_view(data, '1')
    assert figure.data[0].customdata[-1][0] == 10
    assert '抵销后' in note


def export_analysis():
    return {'name': '样本', 'code': 'sh.600219', 'period': '2026-06-30',
            'statement': {'OPERATE_INCOME': 100, 'OPERATE_COST': 60}}


def test_export_rejects_previous_period_before_writing(monkeypatch):
    import pytest
    import gradio as gr
    import profit_ui
    monkeypatch.setattr('tools._resolve.resolve_stock', lambda _: ('样本', 'sh.600219'))
    monkeypatch.setattr(profit_ui, 'save_research_run', lambda *_: pytest.fail('stale export written'))
    with pytest.raises(gr.Error):
        profit_ui.export_evidence(export_analysis(), '样本', '2025-12-31')


def test_export_commit_rejects_changed_query_period_and_snapshot(monkeypatch, tmp_path):
    import profit_ui
    monkeypatch.setattr('tools._resolve.resolve_stock', lambda _: ('样本', 'sh.600219'))
    monkeypatch.setattr(profit_ui, 'save_research_run', lambda *_: tmp_path)
    data = export_analysis()
    candidate = profit_ui.export_evidence(data, '样本', data['period'])
    files = profit_ui.commit_export(candidate, '样本', data['period'], data)
    assert files == [str(tmp_path / 'report.md'), str(tmp_path / 'evidence.json')]
    assert profit_ui.commit_export(candidate, '另一公司', data['period'], data) is None
    assert profit_ui.commit_export(candidate, '样本', '2025-12-31', data) is None
    assert profit_ui.commit_export(candidate, '样本', data['period'], None) is None
    refreshed = {**data, 'statement': {'OPERATE_INCOME': 110, 'OPERATE_COST': 60}}
    assert profit_ui.commit_export(candidate, '样本', data['period'], refreshed) is None
