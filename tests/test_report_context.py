import copy
import json
from unittest.mock import patch

import pandas as pd
import pytest
from types import SimpleNamespace

from report_context import build_context, context_payload, save_context


def fixture():
    from scoring import score_observation
    raw = dict(code='sh.601899', as_of='2026-09-06', financial_period='2025-12-31',
               market_date='2026-09-04', roe=10., growth=20., pe=12., ma5=11., ma20=10.,
               ma60=9., dif=1., dea=.5, rsi=50., return20=2., flow_ratio_pct=None,
               debt=50., current=2., source_dates={}, source_details={}, issues=['资金缺项'])
    header = dict(schema_version=2, version='2.0', batch_id='batch-a', as_of='2026-09-06', financial_period='2025-12-31')
    row = dict(code='sh.601899', stock_name='紫金矿业', subindustry='gold',
               **{k: header[k] for k in ('version', 'batch_id', 'as_of', 'financial_period')},
               raw=raw, scores=score_observation(raw))
    return dict(**header, rows=[row])


def profit():
    return dict(code='sh.601899', name='紫金矿业', period='2025-12-31', notice_date='2026-03-21',
                statement={'OPERATE_INCOME': 100.}, segments=[], segment_period=None,
                bridge={}, source={}, warnings=[], business_types=[])


def test_one_snapshot_read_and_explicit_profit_period(tmp_path):
    snap = fixture()
    with patch('report_context.read_snapshot', return_value=snap) as read, \
            patch('report_context.analyze_profit', return_value=profit()) as analyze, \
            patch('report_context.load_macro', return_value=pd.DataFrame()):
        context = build_context('紫金矿业', 'sh.601899')
    read.assert_called_once_with()
    analyze.assert_called_once_with('sh.601899', period='2025-12-31')
    snap['rows'][0]['raw']['pe'] = 999
    payload = context_payload(context)
    assert payload['observation']['pe'] == 12
    assert payload['observation']['flow_ratio_pct'] is None
    assert payload['score_snapshot']['batch_id'] == 'batch-a'
    path = save_context(context, tmp_path)
    assert json.loads(path.read_text(encoding='utf-8'))['score_snapshot'] == fixture()


@pytest.mark.parametrize('field,value', [('period','2026-06-30'), ('code','sh.600000'), ('notice_date','2026-09-07')])
def test_mismatched_or_future_profit_is_withheld(field, value):
    data = profit()
    data[field] = value
    with patch('report_context.read_snapshot', return_value=fixture()), \
            patch('report_context.analyze_profit', return_value=data), \
            patch('report_context.load_macro', return_value=pd.DataFrame()):
        context = build_context('紫金矿业', 'sh.601899')
    assert not context['profit']['statement']
    assert context['warnings']


def test_no_snapshot_does_not_silently_use_live_or_latest_period():
    with patch('report_context.read_snapshot', return_value=None), \
            patch('report_context.analyze_profit') as analyze:
        with pytest.raises(ValueError, match='评分快照'):
            build_context('紫金矿业', 'sh.601899')
    analyze.assert_not_called()


def test_report_does_not_reread_batch_after_model_call(tmp_path):
    import report
    from report_context import save_context as save
    original = fixture()
    prompts = []
    def complete(**kwargs):
        prompts.append(kwargs['messages'][1]['content'])
        original['batch_id'] = 'batch-b'
        original['rows'][0]['raw']['pe'] = 999.
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='## 基本面\n本地财务。\n## 估值\nPE12。\n## 技术面\n均线。\n## 资金面\n缺失。\n## 风险\n非完整风控。'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    with patch('report._resolve_stock', return_value=('紫金矿业', 'sh.601899')), \
            patch('report_context.read_snapshot', return_value=original) as read, \
            patch('report_context.analyze_profit', return_value=profit()), \
            patch('report_context.load_macro', return_value=pd.DataFrame()), \
            patch('report_context.save_context', side_effect=lambda c: save(c, tmp_path)), \
            patch('report.create_llm_client', return_value=client), \
            patch('report.load_llm_config', return_value=SimpleNamespace(model='test')), \
            patch('report.execute_tool', side_effect=AssertionError('unexpected live call')):
        result = list(report.generate_report_iter('紫金矿业'))[-1]
    read.assert_called_once_with()
    assert 'batch-a' in prompts[0] and 'batch-b' not in prompts[0]
    assert result['snapshot_batch'] == 'batch-a'
    assert 'batch-a' in result['radar_note'] and 'batch-b' not in result['radar_note']
    assert result['profit_analysis']['period'] == '2025-12-31'
    saved = json.loads(next(tmp_path.glob('*/context.json')).read_text(encoding='utf-8'))
    assert saved['observation']['pe'] == 12
    assert saved['observation']['flow_ratio_pct'] is None


def test_macro_text_and_plot_use_same_cutoff_data(tmp_path):
    import report_context
    from charts import draw_macro_cycle
    frame = pd.DataFrame({'date':['2026-09-04','2026-09-07'],
        'industrial_metals_state':[1,999], 'precious_metals_state':[2,999],
        'strategic_metals_state':[3,999]})
    path = tmp_path / 'macro.parquet'
    frame.to_parquet(path)
    with patch.object(report_context, 'MACRO', path):
        captured = report_context.load_macro('2026-09-06')
    with patch('charts.pd.read_parquet', side_effect=AssertionError('reread')):
        chart = draw_macro_cycle(frame=captured)
    assert chart.data[0].y.tolist() == [1]


def test_revenue_mix_never_reads_legacy_profile_shares():
    from charts import draw_report_mix
    data = profit()
    data.update(segment_period=data['period'], segments=[
        dict(name='黄金', revenue=60.), dict(name='铜', revenue=40.)])
    with patch('charts.pd.read_parquet', side_effect=AssertionError('reread')):
        fig = draw_report_mix(data)
    assert list(fig.data[0].values) == [.6,.4]
    data['segment_period'] = '2026-06-30'
    assert draw_report_mix(data) is None


def test_captured_operating_disclosure_is_used_by_evidence_and_ui():
    from research_evidence import build_evidence
    from profit_ui import disclosure_view
    data = profit()
    data['_operating_snapshot'] = dict(code=data['code'], period=data['period'],
        data=dict(records=[], products=[], period=data['period'], warnings=['捕获时暂无经营数据']))
    with patch('tools.operating_disclosure.load_operating_disclosure', side_effect=AssertionError('newer file')):
        assert build_evidence(data)
        rendered = disclosure_view(data)
    assert '捕获时暂无经营数据' in str(rendered)


def test_palladium_disclosure_uses_same_identity_for_chart_and_sensitivity():
    from charts import draw_report_mix
    from tools.sensitivity_core import segment_metals, analyze_sensitivity_row
    data = profit()
    data.update(segment_period=data['period'], segments=[dict(name='钯', revenue=100.)])
    metals = segment_metals('钯')
    assert metals == ['palladium']
    with patch('tools.sensitivity_core._load_analysis', side_effect=AssertionError('newer period')):
        result = analyze_sensitivity_row(dict(code=data['code'],stock_name=data['name'],metal_quality='clean'),
                                         metals[0], -10, analysis=data)
    assert result['status'] == 'applicable' and result['amount_yuan'] == -10
    assert list(draw_report_mix(data).data[0].customdata) == ['palladium']
