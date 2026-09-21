import importlib
import math

import pandas as pd
import pytest


@pytest.fixture
def core(tmp_path, monkeypatch):
    module = importlib.import_module('tools.sensitivity_core')
    profile = tmp_path / 'profile.parquet'
    pd.DataFrame([dict(code='sh.600001', stock_name='加工测试', metal_quality='clean')]).to_parquet(profile)
    monkeypatch.setattr(module, 'PROFILE', profile)
    analysis = dict(code='sh.600001', name='加工测试', period='2025-12-31', notice_date='2026-03-01',
        segment_period='2025-12-31', business_types=['processing'],
        statement=dict(OPERATE_INCOME=100e8, PARENT_NETPROFIT=10e8), source={},
        segment_source={'notice_date': None}, segments=[
            dict(name='铜板带', revenue=50e8, excluded=False, is_elimination=False),
            dict(name='其他', revenue=50e8, excluded=False, is_elimination=False)])
    monkeypatch.setattr(module, '_load_analysis', lambda code: analysis)
    return module, analysis, profile


def test_one_percent_revenue_shock_and_positive_profit_comparator(core):
    m, _, _ = core
    out = m.analyze_sensitivity('加工测试', '铜', 1)
    assert out['status'] == 'applicable'
    assert out['quantity_kind'] == 'revenue_change_approximation'
    assert out['amount_yuan'] == pytest.approx(.5e8)
    assert out['percentage'] == pytest.approx(5)
    assert out['one_percent_comparator'] == pytest.approx(5)
    assert out['model'] == 'fixed_volume_revenue_shock'
    assert out['business_types'] == ['processing']
    assert any('成本' in w for w in out['warnings'])


@pytest.mark.parametrize('profit', [0, -10e8, None])
def test_nonpositive_profit_has_no_percentage(core, profit):
    m, a, _ = core
    a['statement']['PARENT_NETPROFIT'] = profit
    result = m.analyze_sensitivity('加工测试', 'copper', -20)
    assert result['amount_yuan'] == -10e8
    assert result['percentage'] is None
    assert result['one_percent_comparator'] is None


@pytest.mark.parametrize('quality', ['merged', 'coarse', 'unknown', None])
def test_unreliable_profile_shares_withheld(core, quality):
    m, _, p = core
    pd.DataFrame([dict(code='sh.600001', stock_name='加工测试', metal_quality=quality)]).to_parquet(p)
    out = m.analyze_sensitivity('加工测试', 'copper', 1)
    assert out['status'] == 'insufficient'
    assert out['amount_yuan'] is None


def test_unknown_metal_exposure_is_not_zero(core):
    m, _, _ = core
    out = m.analyze_sensitivity('加工测试', 'gold', 1)
    assert out['status'] == 'insufficient'
    assert out['amount_yuan'] is None
    assert out['share'] is None


def test_merged_raw_label_withheld_even_if_profile_says_clean(core):
    m, a, _ = core
    a['segments'][0]['name'] = '铜钴产品'
    assert m.analyze_sensitivity('加工测试', 'copper', 1)['amount_yuan'] is None


@pytest.mark.parametrize('shock', [math.nan, math.inf, -math.inf, True, 'bad', -101])
def test_nonfinite_or_impossible_shock_rejected(core, shock):
    m, _, _ = core
    result = m.analyze_sensitivity('加工测试', 'copper', shock)
    assert result['status'] == 'unsupported'
    assert result['amount_yuan'] is None


def test_interim_is_not_annualized_and_mismatch_is_withheld(core):
    m, a, _ = core
    a['period'] = a['segment_period'] = '2026-06-30'
    out = m.analyze_sensitivity('加工测试', 'copper', 1)
    assert out['amount_yuan'] == .5e8
    assert out['period'] == '2026-06-30'
    a['segment_period'] = '2025-12-31'
    assert m.analyze_sensitivity('加工测试', 'copper', 1)['amount_yuan'] is None


def test_single_stock_and_matrix_identical(core, monkeypatch):
    m, _, p = core
    from tools import sector_matrix, price_sensitivity
    monkeypatch.setattr(sector_matrix, 'PROFILE', p)
    result = m.analyze_sensitivity('加工测试', 'copper', 1)
    row = sector_matrix.compute_matrix('copper', 1).iloc[0]
    for key in ('code', 'period', 'status', 'quantity_kind', 'amount_yuan', 'percentage'):
        assert row[key] == result[key]
    text = price_sensitivity.estimate_price_sensitivity('加工测试', 'copper', 1)
    assert '5.0%' in text
    assert '500.0%' not in text
    assert '经验校准' not in text
    assert '年化' not in text


def test_revenue_totals_or_hierarchy_invalid(core):
    m, a, _ = core
    a['segments'][1]['revenue'] = 40e8
    assert m.analyze_sensitivity('加工测试', 'copper', 1)['amount_yuan'] is None
    a['segments'][1]['revenue'] = 50e8
    a['segments'][0]['excluded'] = True
    assert m.analyze_sensitivity('加工测试', 'copper', 1)['amount_yuan'] is None


def test_classify_business_has_no_default_rate(monkeypatch):
    from tools import _resolve, profit_analysis
    monkeypatch.setattr(profit_analysis, 'analyze_profit', lambda q: {'business_types': ['processing']})
    rate, label = _resolve.classify_business('sh.600001')
    assert rate is None
    assert '加工' in label


def test_platinum_and_palladium_are_not_the_same_exposure(core):
    m, a, _ = core
    a['segments'][0]['name'] = '铂产品'
    assert m.analyze_sensitivity('加工测试', '钯', 1)['amount_yuan'] is None
    assert m.analyze_sensitivity('加工测试', '铂', 1)['amount_yuan'] == .5e8
    a['segments'][0]['name'] = '铂钯产品'
    assert m.analyze_sensitivity('加工测试', '铂', 1)['amount_yuan'] is None
