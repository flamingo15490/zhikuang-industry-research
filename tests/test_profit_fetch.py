import importlib

import pandas as pd
import pytest


def fetcher():
    try:
        return importlib.import_module("scripts.fetch_profit_details")
    except ModuleNotFoundError:
        pytest.fail("Complete profit statement fetcher is missing")


def test_select_dates_newest_unique_and_not_future():
    m = fetcher()
    rows = [{"REPORT_DATE": x} for x in ["2025-12-31 00:00:00", "2026-06-30 00:00:00", "2025-12-31 00:00:00", "2027-03-31 00:00:00", "2026-03-31 00:00:00"]]
    assert m.select_dates(rows, 2, today="2026-09-06") == ["2026-06-30", "2026-03-31"]


def test_empty_response_cannot_create_snapshot(tmp_path, monkeypatch):
    m = fetcher()
    monkeypatch.setattr(m, "request_data", lambda *args, **kwargs: [])
    result = m.fetch_company("sh.601899", tmp_path)
    assert result["status"] == "failed"
    assert result["error"]
    assert not list(tmp_path.glob("*.parquet"))


def test_full_fields_provenance_cache_isolation_and_resume(tmp_path, monkeypatch):
    m = fetcher()
    original = tmp_path / "company_profile"
    original.mkdir()
    annual = original / "profit_sh.601899.parquet"
    annual.write_bytes(b"original annual snapshot")
    dates = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
    batches = []

    def response(url, params):
        if "DateAjax" in url:
            return [{"REPORT_DATE": d + " 00:00:00"} for d in reversed(dates)]
        selected = params["dates"].split(",")
        batches.append(selected)
        return [{"SECURITY_CODE": "601899", "REPORT_DATE": d + " 00:00:00", "OPERATE_INCOME": 100, "OTHER_FIELD": -3} for d in selected]

    monkeypatch.setattr(m, "request_data", response)
    output = tmp_path / "profit_analysis"
    result = m.fetch_company("sh.601899", output)
    assert result["status"] == "success"
    frame = pd.read_parquet(output / "profit_sh.601899.parquet")
    assert len(frame) == 8
    assert frame["REPORT_DATE"].iloc[0] == "2026-06-30 00:00:00"
    assert frame["OTHER_FIELD"].eq(-3).all()
    assert frame["source_url"].str.startswith("https://").all()
    assert pd.to_datetime(frame["fetched_at"], utc=True).notna().all()
    assert all(len(batch) <= 5 for batch in batches)
    assert annual.read_bytes() == b"original annual snapshot"
    monkeypatch.setattr(m, "request_data", lambda *args: pytest.fail("Fresh successful snapshot should resume"))
    assert m.fetch_company("sh.601899", output)["status"] == "cached"


@pytest.mark.parametrize("problem", ["wrong_symbol", "duplicate", "wrong_date", "missing_period"])
def test_invalid_rows_do_not_replace_snapshot(tmp_path, monkeypatch, problem):
    m = fetcher()
    destination = tmp_path / "profit_sh.601899.parquet"
    destination.write_bytes(b"old snapshot")

    def response(url, params):
        if "DateAjax" in url:
            return [{"REPORT_DATE": "2025-12-31"}, {"REPORT_DATE": "2025-09-30"}]
        rows = [{"SECURITY_CODE": "601899", "REPORT_DATE": d, "OPERATE_INCOME": 100} for d in params["dates"].split(",")]
        if problem == "wrong_symbol":
            rows[0]["SECURITY_CODE"] = "600000"
        elif problem == "duplicate":
            rows.append(dict(rows[0]))
        elif problem == "wrong_date":
            rows[0]["REPORT_DATE"] = "2024-12-31"
        else:
            rows.pop()
        return rows

    monkeypatch.setattr(m, "request_data", response)
    assert m.fetch_company("sh.601899", tmp_path)["status"] == "failed"
    assert destination.read_bytes() == b"old snapshot"


def test_original_cache_directory_is_rejected(tmp_path, monkeypatch):
    m = fetcher()
    monkeypatch.setattr(m, "PROJECT", tmp_path)
    result = m.fetch_company("sh.601899", tmp_path / "data" / "company_profile")
    assert result["status"] == "failed"
    assert "read-only" in result["error"]


def test_network_retries_are_bounded(monkeypatch):
    m = fetcher()
    attempts = []

    def timeout(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        raise m.requests.Timeout("source unavailable")

    monkeypatch.setattr(m.requests, "get", timeout)
    monkeypatch.setattr(m.time, "sleep", lambda delay: None)
    with pytest.raises(m.requests.Timeout):
        m.request_data(m.DATE_URL, {})
    assert len(attempts) == 3
    assert all(max(timeout) <= 30 for timeout in attempts)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), "not a number", "100", True])
def test_non_numeric_or_nonfinite_financial_value_cannot_replace_snapshot(tmp_path, monkeypatch, value):
    m = fetcher()
    path = tmp_path / "profit_sh.601899.parquet"
    path.write_bytes(b"previous snapshot")

    def response(url, params):
        if "DateAjax" in url:
            return [{"REPORT_DATE": "2025-12-31"}]
        return [{"SECURITY_CODE": "601899", "REPORT_DATE": "2025-12-31", "OPERATE_INCOME": value}]

    monkeypatch.setattr(m, "request_data", response)
    result = m.fetch_company("sh.601899", tmp_path)
    assert result["status"] == "failed"
    assert path.read_bytes() == b"previous snapshot"


def test_zero_revenue_is_a_valid_financial_value():
    m = fetcher()
    m.validate_rows([{"SECURITY_CODE": "601899", "REPORT_DATE": "2025-12-31", "OPERATE_INCOME": 0}],
                    "sh.601899", ["2025-12-31"])
