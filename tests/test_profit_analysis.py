import importlib

import pandas as pd
import pytest


@pytest.fixture
def engine(tmp_path, monkeypatch):
    m = importlib.import_module('tools.profit_analysis')
    monkeypatch.setattr(m, 'BASE', tmp_path)
    monkeypatch.setattr(m, 'resolve_stock', lambda q: ('测试', 'sh.600001'))
    (tmp_path / 'data/profit_analysis').mkdir(parents=True)
    (tmp_path / 'data/company_profile').mkdir()
    return m


def statement(engine, **kwargs):
    row = dict(REPORT_DATE='2025-12-31', NOTICE_DATE='2026-03-01',
               OPERATE_INCOME=100., OPERATE_COST=60., TOTAL_PROFIT=25.,
               INCOME_TAX=5., NETPROFIT=20., MINORITY_INTEREST=2.,
               PARENT_NETPROFIT=18., SALE_EXPENSE=10., MANAGE_EXPENSE=6.,
               INVEST_INCOME=1.)
    row.update(kwargs)
    pd.DataFrame([row]).to_parquet(engine.BASE / 'data/profit_analysis/profit_sh.600001.parquet')


def segments(engine, rows):
    result = []
    for name, revenue, cost, profit, classification, period in rows:
        result.append(dict(zip(['主营构成', '主营收入', '主营成本', '主营利润', '分类类型', '报告日期'],
                               [name, revenue, cost, profit, classification, period])))
    pd.DataFrame(result).to_parquet(engine.BASE / 'data/company_profile/zy_sh.600001.parquet')


def test_complete_bridge(engine):
    statement(engine)
    out = engine.analyze_profit('测试')
    assert out['bridge_status'] == 'complete'
    assert out['reconciliation']['net_profit'] == 0
    assert out['reconciliation']['parent_net_profit'] == 0
    assert out['bridge']['values'][-1] * 1e8 == pytest.approx(18)
    assert '销售费用' in out['bridge']['labels']


def test_missing_tax_does_not_mean_zero(engine):
    statement(engine, INCOME_TAX=None)
    out = engine.analyze_profit('测试')
    assert out['bridge_status'] == 'partial'
    assert '所得税' not in out['bridge']['labels']
    assert out['bridge']['labels'][-1] == '利润总额'


def test_losses_tax_credit_and_minority_loss(engine):
    statement(engine, TOTAL_PROFIT=-10, INCOME_TAX=-3, NETPROFIT=-7,
              MINORITY_INTEREST=-2, PARENT_NETPROFIT=-5)
    out = engine.analyze_profit('测试')
    assert out['bridge_status'] == 'complete'
    assert out['bridge']['values'][out['bridge']['labels'].index('所得税')] > 0
    assert out['bridge']['values'][-1] < 0


def test_residual_and_endpoint_discrepancies_are_explicit(engine):
    statement(engine, TOTAL_PROFIT=30, NETPROFIT=22, PARENT_NETPROFIT=17)
    out = engine.analyze_profit('测试')
    assert out['bridge_status'] == 'inconsistent'
    assert out['reconciliation']['net_profit'] == -3
    assert out['reconciliation']['parent_net_profit'] == -3
    assert '未分类损益差额' in out['bridge']['labels']
    assert '净利润勾稽差异' in out['bridge']['labels']


def test_future_notice_and_report_dates_excluded(engine):
    statement(engine)
    path = engine.BASE / 'data/profit_analysis/profit_sh.600001.parquet'
    df = pd.read_parquet(path)
    future = df.iloc[0].to_dict() | dict(REPORT_DATE='2099-06-30', NOTICE_DATE='2099-08-01')
    future_notice = df.iloc[0].to_dict() | dict(REPORT_DATE='2026-06-30', NOTICE_DATE='2099-08-01')
    pd.concat([df, pd.DataFrame([future, future_notice])]).to_parquet(path)
    assert engine.analyze_profit('测试')['periods'] == ['2025-12-31']
    assert engine.analyze_profit('测试', '2026-06-30')['bridge_status'] == 'missing'


def test_segments_dimension_child_elimination_and_missing(engine):
    statement(engine)
    rows = [('矿山采选', 80, 40, 40, '按产品分类', '2025-12-31'),
            ('其中:铜矿', 50, 20, 30, '按产品分类', '2025-12-31'),
            ('内部销售抵销', -10, -5, -5, '按产品分类', '2025-12-31'),
            ('贸易业务', 30, None, None, '按产品分类', '2025-12-31'),
            ('行业总计', 100, 60, 40, '按行业分类', '2025-12-31')]
    segments(engine, rows)
    out = engine.analyze_profit('测试')
    assert len(out['segments']) == 4
    assert out['segments'][1]['excluded']
    assert out['segments'][2]['gross_profit'] == -5
    assert out['segments'][3]['gross_profit'] is None
    assert out['segment_status'] == 'comparison_only'
    assert set(out['business_types']) == {'mining', 'trading'}
    assert all(r['contribution'] is None for r in out['segments'])


def test_verified_segment_contributions(engine):
    statement(engine)
    segments(engine, [('铝板带箔', 100, 60, 40, '按产品分类', '2025-12-31')])
    out = engine.analyze_profit('测试')
    assert out['segment_status'] == 'verified'
    assert out['segments'][0]['contribution'] == 1
    assert out['business_types'] == ['processing']


def test_mismatched_period_and_reported_profit(engine):
    statement(engine)
    segments(engine, [('阴极铜', 100, 60, 60, '按产品分类', '2026-06-30')])
    out = engine.analyze_profit('测试')
    assert out['segment_status'] == 'period_mismatch'
    assert out['segments'][0]['status'] == 'inconsistent'
    assert out['segments'][0]['excluded']
    assert out['business_types'] == []


def test_old_impairment_expense_and_new_signed_impairment_not_double_counted(engine):
    statement(engine, ASSET_IMPAIRMENT_LOSS=4, CREDIT_IMPAIRMENT_LOSS=3,
              ASSET_IMPAIRMENT_INCOME=-2)
    out = engine.analyze_profit('测试')
    b = out['bridge']
    assert b['values'][b['labels'].index('资产减值损益')] * 1e8 == -2
    assert b['values'][b['labels'].index('信用减值损益')] * 1e8 == pytest.approx(-3)


def test_million_yuan_discrepancy_not_hidden_in_large_company(engine):
    statement(engine, TOTAL_PROFIT=1e12, INCOME_TAX=2e11, NETPROFIT=8e11 + 1e6,
              MINORITY_INTEREST=0, PARENT_NETPROFIT=8e11 + 1e6)
    out = engine.analyze_profit('测试')
    assert out['bridge_status'] == 'inconsistent'


def test_duplicate_and_nonfinite_segments_prevent_contributions(engine):
    statement(engine)
    segments(engine, [('铜精矿', 100, 60, 40, '按产品分类', '2025-12-31'),
                      ('铜精矿', 100, 60, 40, '按产品分类', '2025-12-31'),
                      ('其他', float('inf'), 10, None, '按产品分类', '2025-12-31')])
    out = engine.analyze_profit('测试')
    assert out['segments'][1]['excluded']
    assert out['segments'][2]['gross_profit'] is None
    assert out['segment_status'] == 'comparison_only'
    assert out['business_types'] == []


def test_fallback_keeps_older_period_and_json_has_no_nan(engine):
    statement(engine)
    path = engine.BASE / 'data/profit_analysis/profit_sh.600001.parquet'
    annual = pd.read_parquet(path)
    annual['REPORT_DATE'] = '2024-12-31'
    annual.to_parquet(engine.BASE / 'data/company_profile/profit_sh.600001.parquet')
    out = engine.analyze_profit('测试', '2024-12-31')
    assert out['source']['kind'] == 'annual_fallback'
    assert out['periods'] == ['2025-12-31', '2024-12-31']
    assert 'NaN' not in engine.get_profit_analysis('测试')


def test_reported_operating_to_total_discrepancy_is_not_hidden(engine):
    statement(engine, OPERATE_PROFIT=24, NONBUSINESS_INCOME=4, NONBUSINESS_EXPENSE=1)
    out = engine.analyze_profit('测试')
    assert out['reconciliation']['operating_to_total'] == -2
    assert out['bridge_status'] == 'inconsistent'
    assert '利润总额勾稽差异' in out['bridge']['labels']


@pytest.mark.parametrize('label,expected', [
    ('冶炼产碳酸锂', ['refining']),
    ('冶炼产铜', []),
    ('贸易精炼等其他销售收入', ['trading']),
    ('外购精矿冶炼', ['smelting']),
    ('铜冶炼TC/RC加工费', ['smelting', 'processing']),
    ('原铝板块', ['aluminum']),
    ('矿山工程建设', []),
    ('矿山机械设备', []),
    ('矿山设计咨询', []),
    ('采矿运营管理', []),
])
def test_external_concentrate_model_requires_explicit_evidence(engine, label, expected):
    assert engine._business_types([label]) == expected


def test_default_selects_latest_common_period_but_explicit_period_is_preserved(engine):
    statement(engine)
    path = engine.BASE / 'data/profit_analysis/profit_sh.600001.parquet'
    df = pd.read_parquet(path)
    newer = df.iloc[0].to_dict() | dict(REPORT_DATE='2026-06-30', NOTICE_DATE='2026-08-15')
    pd.concat([df, pd.DataFrame([newer])]).to_parquet(path)
    segments(engine, [('铝箔', 100, 60, 40, '按产品分类', '2025-12-31')])
    default = engine.analyze_profit('测试')
    assert default['period'] == '2025-12-31'
    assert default['periods'] == ['2026-06-30', '2025-12-31']
    assert default['segment_status'] == 'verified'
    explicit = engine.analyze_profit('测试', '2026-06-30')
    assert explicit['period'] == '2026-06-30'
    assert explicit['segment_period'] == '2025-12-31'
    assert explicit['segment_status'] == 'period_mismatch'
