import math

import pandas as pd
import pytest

from tools import aluminum_spread, company_profile
from tools.profit_scenarios import calculate_scenario


@pytest.mark.parametrize('electricity', [math.nan, math.inf, -math.inf, -0.1, True, 'bad'])
def test_legacy_aluminum_rejects_invalid_electricity(electricity):
    with pytest.raises(ValueError):
        aluminum_spread.get_aluminum_profit(electricity)


def test_legacy_aluminum_uses_latest_eligible_sorted_prices(tmp_path, monkeypatch):
    path = tmp_path / 'prices.parquet'
    pd.DataFrame({'date': ['2026-01-02', '2099-01-01', '2026-01-01'],
                  'aluminum': [20000, 99999, 19000], 'alumina': [3000, 99999, 2800]}).to_parquet(path)
    monkeypatch.setattr(aluminum_spread, 'METAL', path)
    text = aluminum_spread.get_aluminum_profit(.45)
    assert '2026-01-02' in text
    assert '2099' not in text
    expected = calculate_scenario('aluminum', dict(price=20000, alumina_price=3000,
        alumina_consumption=1.93, power_consumption=13500, electricity_price=.45, other_cost=2500))['total']
    assert f'{expected:.0f}' in text
    assert '行业假设' in text and '非公司' in text
    assert '适用公司' not in text
    assert '历史分位' not in text


def test_legacy_aluminum_future_only_has_no_amount(tmp_path, monkeypatch):
    path = tmp_path / 'prices.parquet'
    pd.DataFrame({'date': ['2099-01-01'], 'aluminum': [99999], 'alumina': [99999]}).to_parquet(path)
    monkeypatch.setattr(aluminum_spread, 'METAL', path)
    assert aluminum_spread.get_aluminum_profit().startswith('错误')


def test_profile_does_not_attach_statement_period_to_undated_metal_shares(tmp_path, monkeypatch):
    path = tmp_path / 'profile.parquet'
    pd.DataFrame([dict(code='sh.600219', stock_name='南山铝业', report_date='2025-12-31',
        notice_date='2026-03-27', tax_rate=.1, minority_share=.2, metal_quality='clean', aluminum_share=1.)]).to_parquet(path)
    monkeypatch.setattr(company_profile, 'PROFILE', path)
    text = company_profile.get_company_profile('南山铝业')
    assert 'aluminum=100%' not in text
    assert 'get_profit_analysis' in text
    assert '占比期间未核验' in text
    assert '税率' in text and '2025-12-31' in text
