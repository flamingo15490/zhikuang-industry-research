import pandas as pd
import pytest

from tools import _resolve, company_profile


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    path = tmp_path / 'profiles.parquet'
    records = [
        ('sh.900001', 'prefix sh.600219 600219'),
        ('sh.600219', '\u5357\u5c71\u94dd\u4e1a'),
        ('sh.601600', '\u4e2d\u56fd\u94dd\u4e1a'),
        ('sh.900002', '\u5357\u5c71\u94dd\u4e1a suffix'),
        ('sh.900003', 'Literal[Name'),
    ]
    pd.DataFrame([dict(code=code, stock_name=name, report_date='2025-12-31',
        notice_date='2026-03-01', tax_rate=.1, minority_share=.2, metal_quality='clean')
        for code, name in records]).to_parquet(path)
    monkeypatch.setattr(_resolve, 'PROFILE', path)
    monkeypatch.setattr(company_profile, 'PROFILE', path)


@pytest.mark.parametrize('query', ['', '   ', '\u94dd', 'missing'])
def test_shared_resolution_rejects_empty_ambiguous_and_missing(profiles, query):
    assert _resolve.resolve_stock(query) == (None, None)


@pytest.mark.parametrize('query', [' SH.600219 ', '600219', '\u5357\u5c71\u94dd\u4e1a'])
def test_shared_resolution_prefers_exact_identity(profiles, query):
    assert _resolve.resolve_stock(query) == ('\u5357\u5c71\u94dd\u4e1a', 'sh.600219')


def test_shared_resolution_treats_regex_characters_literally(profiles):
    assert _resolve.resolve_stock('[') == ('Literal[Name', 'sh.900003')
    assert _resolve.resolve_stock('.*') == (None, None)


@pytest.mark.parametrize('query', ['', '   ', '\u94dd', '.*'])
def test_profile_never_returns_arbitrary_company(profiles, query):
    text = company_profile.get_company_profile(query)
    assert '\u7ecf\u8425\u753b\u50cf' not in text


@pytest.mark.parametrize('query', [' SH.600219 ', '600219', '\u5357\u5c71\u94dd\u4e1a'])
def test_profile_uses_exact_identity_before_substring(profiles, query):
    assert company_profile.get_company_profile(query).startswith('\u5357\u5c71\u94dd\u4e1a\uff08sh.600219\uff09')


def test_profile_supports_literal_unique_substring(profiles):
    assert company_profile.get_company_profile('[').startswith('Literal[Name')
