"""Synthetic fixtures only: no licensed observations in the repository."""
import pytest
from wind_local import FIELDS, financial_records, market_records, number


def financial_row(period, parent=30, minority=10):
    values = dict(assets=200, liabilities=80, current_assets=70, current_liabilities=35,
                  revenue=150, cost=100, total_profit=50, net_profit=parent+minority, minority=minority)
    return ['示例\n600000.SH', period, *(values[k] for k in FIELDS)]


def test_financial_identities_and_annual_growth():
    header = ['', '', *(label+'\n[报表类型] 合并报表\n[单位] 元' for label in FIELDS.values())]
    rows, skipped = financial_records([header, financial_row('2024/12/31',20), financial_row('2025/12/31'),
                                       financial_row('2026/9/9')], '2026-09-08')
    v = rows[-1]['values']
    assert skipped == 1
    assert v['parent_profit'] == 30
    assert v['tax_difference'] == 10
    assert v['gross_profit'] == 50
    assert v['debt_pct'] == 40
    assert v['current_ratio'] == 2
    assert v['annual_growth_pct'] == 50
    assert v['weighted_roe'] is None
    assert rows[-1]['announcement_date'] is None


def test_missing_zero_loss_and_duplicate_period():
    header = ['', '', *(label+'\n合并报表\n[单位] 元' for label in FIELDS.values())]
    row = financial_row('2025/12/31')
    row[2+list(FIELDS).index('minority')] = None
    parsed, _ = financial_records([header, financial_row('2024/12/31',-20), row], '2026-09-08')
    assert parsed[-1]['values']['parent_profit'] is None
    assert parsed[-1]['values']['annual_growth_pct'] is None
    assert number('0') == 0
    assert number('nan') is None
    assert number('--') is None
    with pytest.raises(ValueError, match='重复'):
        financial_records([header, row, row], '2026-09-08')


def test_market_does_not_shift_previous_close_or_accept_suspension():
    header = ['', '', '前收盘价 前复权 [单位] 元', '收盘价 不复权 [单位] 元',
              '成交额 [单位] 元','成交量 [单位] 股','停牌原因','市盈率PE(TTM) [单位] 倍']
    rows, skipped = market_records([header,
        ['示例\n600000.SH','2026/9/7','5','6','1,000','100','','-2'],
        ['','2026/9/8','6','6','1,000','100','重大事项','-2'],
        ['','2026/9/9','6','6','1,000','100','','-2']], '2026-09-08')
    assert skipped == 1
    assert rows[0]['pe_ttm'] == -2
    assert rows[0]['qfq_close'] is None
    assert rows[0]['technical'] is None
    assert rows[1]['close_unadjusted'] is None
