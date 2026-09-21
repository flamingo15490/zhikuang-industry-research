import pandas as pd
import pytest
import report


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    path=tmp_path/'profile.parquet'
    pd.DataFrame([{'code':'sh.600219','stock_name':'南山铝业'},
                  {'code':'sh.601600','stock_name':'中国铝业'}]).to_parquet(path)
    monkeypatch.setattr(report, 'PROFILE', path)
    monkeypatch.setattr(report, 'FUND', tmp_path/'absent.parquet')


@pytest.mark.parametrize('query',['','铝','.*','['])
def test_report_rejects_ambiguous_and_regex_inputs(profiles,query):
    with pytest.raises(ValueError):
        report._resolve_stock(query)


def test_report_exact_identity(profiles):
    assert report._resolve_stock('600219') == ('南山铝业','sh.600219')
