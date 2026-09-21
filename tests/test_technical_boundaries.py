from unittest.mock import patch

import pytest

from tools.technical import _rsi, get_technical_indicator


@pytest.mark.parametrize('closes,expected', [([10.0] * 80, 50.0),
                                           (list(range(1, 81)), 100.0),
                                           (list(range(80, 0, -1)), 0.0),
                                           ([10.0] * 14, None)])
def test_rsi_boundaries(closes, expected):
    assert _rsi(closes) == expected


def test_zero_rsi_is_reported_as_oversold():
    rows = [['2026-09-04', '1', str(value)] for value in range(80, 0, -1)]
    with patch('tools.technical.resolve_stock', return_value=('测试', 'sh.600000')), \
            patch('tools.technical._fetch_kline', return_value=rows):
        result = get_technical_indicator('600000')
    assert 'RSI(14)：0.0（超卖）' in result
