import pytest

from onboarding import next_step, STEPS, load_intro


def test_tutorial_waits_for_company_data_and_matrix_result():
    assert next_step(0, None, '') == 0
    assert next_step(0, {'code':'sh.600219'}, '') == 1
    assert next_step(5, {'code':'sh.600219'}, '') == 5
    assert next_step(5, {'code':'sh.600219'}, '数据不足，无法计算') == 6
    assert next_step(len(STEPS)-1, {}, '') == len(STEPS)-1


def test_intro_uses_local_context_without_model(monkeypatch):
    import report
    import report_context
    monkeypatch.setattr(report, '_resolve_stock', lambda query: ('南山铝业', 'sh.600219'))
    monkeypatch.setattr(report_context, 'build_context', lambda name, code: (_ for _ in ()).throw(ValueError('缺少评分快照')))
    result = load_intro('南山铝业')
    assert result['ok'] is False
    assert '缺少评分快照' in result['message']
