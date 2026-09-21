import pytest
from scripts.verify_wind_technical import compare


def test_identical_series_passes_all_windows():
    values=[10+i*.01+(i%7)*.02 for i in range(100)]
    result=compare(values,values)
    assert result['passed']
    assert not result['changed_windows']


def test_same_trend_score_does_not_excuse_price_error():
    values=[10+i*.1 for i in range(100)]
    result=compare(values,[v*1.03 for v in values])
    assert not result['passed']
    assert result['price_max_relative_pct']>2.9


def test_short_or_unaligned_history_rejected():
    with pytest.raises(ValueError):
        compare([1]*79,[1]*79)
    with pytest.raises(ValueError):
        compare([1]*100,[1]*99)
