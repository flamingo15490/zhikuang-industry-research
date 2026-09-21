from datetime import date, timedelta
from unittest.mock import patch

import pytest

from tools import technical as tech


def snapshot():
    today = date.today()
    rows = [[(today - timedelta(days=80-i)).isoformat(), '10', str(10 + i / 100)] for i in range(80)]
    day = rows[-1][0]
    header = dict(schema_version=2, version='2.0', batch_id='test',
                  as_of=today.isoformat(), financial_period='2025-12-31')
    row = dict(code='sh.601899', stock_name='紫金矿业', **{k: header[k] for k in ('version','batch_id','as_of','financial_period')})
    row['raw'] = dict(code=row['code'], as_of=header['as_of'], financial_period=header['financial_period'],
                      market_date=day, source_dates={'technical': day},
                      source_details={'technical': {'adjustment': 'qfq', 'data_field': 'qfqday', 'rows': rows}})
    return dict(**header, rows=[row])


def test_http_failure_uses_dated_snapshot_with_disclosure():
    with patch.object(tech, '_fetch_kline', side_effect=OSError('offline')), \
            patch('score_view.read_snapshot', return_value=snapshot()):
        result = tech.get_technical_indicator('601899')
    assert '本地行情快照' in result and '实时接口不可用' in result
    assert 'MA5' in result and '技术面获取失败' not in result


@pytest.mark.parametrize('damage', ['stale', 'mixed', 'unadjusted', 'future', 'duplicate', 'invalid'])
def test_unusable_snapshot_cannot_silently_replace_live(damage):
    data = snapshot()
    row = data['rows'][0]
    detail = row['raw']['source_details']['technical']
    if damage == 'stale':
        for point in detail['rows']:
            point[0] = (date.fromisoformat(point[0]) - timedelta(days=10)).isoformat()
        row['raw']['market_date'] = row['raw']['source_dates']['technical'] = detail['rows'][-1][0]
    elif damage == 'mixed':
        row['batch_id'] = 'other'
    elif damage == 'unadjusted':
        detail['adjustment'] = 'none'
    elif damage == 'future':
        data['as_of'] = row['as_of'] = (date.today() + timedelta(days=1)).isoformat()
    elif damage == 'duplicate':
        data['rows'].append(row)
    else:
        detail['rows'][-1][2] = 'NaN'
    with patch.object(tech, '_fetch_kline', side_effect=OSError('offline')), \
            patch('score_view.read_snapshot', return_value=data):
        result = tech.get_technical_indicator('601899')
    assert '技术面获取失败' in result
