import pandas as pd

import score_data as sd


def test_financial_period_and_announcement_cutoff():
    frame = pd.DataFrame([
        dict(report_period='2025-12-31', ann_date='2026-04-01', roe=12),
        dict(report_period='2026-06-30', ann_date='2026-08-01', roe=99),
        dict(report_period='2025-12-31', ann_date='2026-09-07', roe=88),
    ])
    assert sd.select_period(frame, '2025-12-31', '2026-09-06', 'report_period', 'ann_date')['roe'] == 12


def test_unknown_announcement_is_not_point_in_time():
    frame = pd.DataFrame([dict(report_period='2025-12-31', ann_date=None, roe=12)])
    assert sd.select_period(frame, '2025-12-31', '2026-09-06', 'report_period', 'ann_date') is None


def test_growth_negative_or_zero_base_is_missing():
    assert sd.profit_growth(10, -5) is None
    assert sd.profit_growth(10, 0) is None
    assert sd.profit_growth(-5, 10) == -150
    assert sd.number(True) is None
    assert sd.number(False) is None


def test_kline_sorts_deduplicates_and_excludes_future():
    rows = [['2026-09-04', '1', '4'], ['2026-09-03', '1', '3'], ['2026-09-04', '1', '4'], ['2026-09-07', '1', '7']]
    assert [r[0] for r in sd.clean_kline(rows, '2026-09-06')] == ['2026-09-03', '2026-09-04']


def test_conflicting_duplicate_kline_is_rejected():
    import pytest
    with pytest.raises(ValueError, match='conflicting'):
        sd.clean_kline([['2026-09-04', 1, 4], ['2026-09-04', 1, 5]], '2026-09-06')


def test_quote_actual_timestamp_and_no_fabricated_history():
    fields = [''] * 50
    fields[30], fields[39] = '20260904150000', '11.2'
    quote = 'v_sh601899="' + '~'.join(fields) + '";'
    assert sd.parse_quote(quote, '2026-09-06') == (11.2, '2026-09-04')
    assert sd.parse_quote(quote, '2026-09-03') == (None, '2026-09-04')


def test_unverified_flow_units_never_normalized():
    assert sd.normalize_flow([{'date': '2026-09-04', 'r0_net': 10, 'amount': 100}], ['2026-09-04'], False) is None


def test_flow_requires_five_exact_dates_and_positive_amount():
    dates = ['2026-08-31', '2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04']
    rows = [dict(date=d, r0_net=-10, amount=100) for d in dates]
    assert sd.normalize_flow(rows, dates, True) == -10
    assert sd.normalize_flow(rows[:-1], dates, True) is None
    rows[0]['amount'] = 0
    assert sd.normalize_flow(rows, dates, True) is None
    rows[0]['amount'] = 5
    assert sd.normalize_flow(rows, dates, True) is None


def mock_sources(monkeypatch, quote_day='20260904150000', kline_end='2026-09-04', fail=False):
    monkeypatch.setattr(sd, '_financial', lambda raw: None)
    dates = pd.bdate_range(end=kline_end, periods=80).strftime('%Y-%m-%d').tolist()
    rows = [[d, '10', str(10 + i / 10)] for i, d in enumerate(dates)]
    fields = [''] * 50
    fields[30], fields[39] = quote_day, '15'
    def fetch(url):
        if fail:
            raise OSError('offline')
        if 'qt.gtimg' in url:
            return 'v="' + '~'.join(fields) + '";'
        if 'fqkline' in url:
            return sd.json.dumps({'data': {'sh601899': {'qfqday': rows}}})
        if 'MoneyFlow' in url:
            return sd.json.dumps([{'opendate': d, 'r0_net': '-10'} for d in dates[-5:]])
        return sd.json.dumps({'data': {'klines': [d + ',1,1,1,1,1,100' for d in dates[-5:]]}})
    monkeypatch.setattr(sd, '_fetch', fetch)


def test_collector_all_market_sources_same_date(monkeypatch):
    mock_sources(monkeypatch)
    raw = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    assert raw['pe'] == 15
    assert raw['flow_ratio_pct'] == -10
    assert raw['market_date'] == raw['source_dates']['pe'] == raw['source_dates']['flow_ratio_pct'] == '2026-09-04'
    assert all(raw[key] is not None for key in sd.TECH)


def test_quote_mismatch_does_not_score_latest_pe_as_historical(monkeypatch):
    mock_sources(monkeypatch, quote_day='20260903150000')
    raw = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    assert raw['pe'] is None
    assert any('does not match' in issue for issue in raw['issues'])


def test_stale_market_data_withheld(monkeypatch):
    mock_sources(monkeypatch, quote_day='20260828150000', kline_end='2026-08-28')
    raw = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    assert all(raw[key] is None for key in ('pe', 'flow_ratio_pct', *sd.TECH))
    assert raw['source_dates']['pe'] == '2026-08-28'


def test_source_failure_remains_missing(monkeypatch):
    mock_sources(monkeypatch, fail=True)
    raw = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    assert all(raw[key] is None for key in sd.METRICS)
    assert len(raw['issues']) == 3


def test_atomic_write_preserves_previous_on_invalid_payload(tmp_path):
    import pytest
    from scripts.build_radar_scores import atomic_write
    path = tmp_path / 'current.json'
    atomic_write(path, {'batch_id': 'previous'})
    with pytest.raises(ValueError):
        atomic_write(path, {'invalid': float('nan')})
    assert sd.json.loads(path.read_text()) == {'batch_id': 'previous'}
    assert list(tmp_path.glob('*.tmp')) == []


def test_retry_rejects_mixed_raw_asof(tmp_path):
    import pytest
    from scripts.build_radar_scores import build_snapshot, VERSION
    context = dict(version=VERSION, batch_id='old', as_of='2026-09-06', financial_period='2025-12-31')
    row = dict(**context, code='sh.601899', raw=dict(code='sh.601899', as_of='2026-09-05', financial_period='2025-12-31'))
    path = tmp_path / 'mixed.json'
    path.write_text(sd.json.dumps(dict(**context, rows=[row])))
    with pytest.raises(ValueError, match='observation context'):
        build_snapshot('2026-09-06', '2025-12-31', retry_network=path)


def test_financial_cache_context_cannot_leak(monkeypatch):
    import pytest
    mock_sources(monkeypatch)
    with pytest.raises(ValueError, match='context mismatch'):
        sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31',
            financial_cache=dict(code='sh.601899', as_of='2026-09-05', financial_period='2025-12-31'))


def test_sohu_amount_uses_documented_ten_thousand_yuan(monkeypatch):
    payload = [{'status': 0, 'hq': [['2026-09-04', '1','1','0','0%','1','1','100','593906.06']]}]
    monkeypatch.setattr(sd, '_fetch', lambda url: sd.json.dumps(payload))
    result = sd._sohu_amount_rows('http://example.test')
    assert result[0]['amount'] == 5939060600
    assert result[0]['raw_unit'] == '10000 CNY'
    assert result[0]['date'] == '2026-09-04'


def test_unadjusted_daily_data_cannot_masquerade_as_qfq(monkeypatch):
    mock_sources(monkeypatch)
    fetch = sd._fetch
    def unadjusted(url):
        return fetch(url).replace('qfqday', 'day') if 'fqkline' in url else fetch(url)
    monkeypatch.setattr(sd, '_fetch', unadjusted)
    raw = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    assert all(raw[key] is None for key in sd.TECH)
    assert any('unadjusted day cannot substitute' in issue for issue in raw['issues'])


def test_retry_flow_preserves_successful_quote_and_technical(monkeypatch):
    mock_sources(monkeypatch)
    prior = sd.collect_observation('Test', 'sh.601899', '2026-09-06', '2025-12-31')
    prior['flow_ratio_pct'] = None
    prior['issues'] = ['flow_ratio_pct: RemoteDisconnected']
    def only_amount(url):
        assert 'push2his.eastmoney' in url
        dates = prior['source_details']['technical']['trading_dates'][-5:]
        return sd.json.dumps({'data': {'klines': [d + ',1,1,1,1,1,100' for d in dates]}})
    monkeypatch.setattr(sd, '_fetch', only_amount)
    result = sd.retry_observation(prior)
    assert result['flow_ratio_pct'] == -10
    assert result['pe'] == prior['pe']
    assert all(result[key] == prior[key] for key in sd.TECH)
    assert result['source_dates']['pe'] == prior['source_dates']['pe']
    assert prior['flow_ratio_pct'] is None
