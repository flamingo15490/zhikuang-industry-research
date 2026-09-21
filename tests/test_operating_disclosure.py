import importlib
import json

import pytest


def module():
    try:
        return importlib.import_module("tools.operating_disclosure")
    except ModuleNotFoundError:
        pytest.fail("Operating disclosure loader is missing")


def record(metric, value, **changes):
    return dict({"code": "sh.601899", "period": "2026-06-30", "commodity": "冶炼产锌",
                 "metric": metric, "value": value, "unit": "元/吨", "scope": "抵销前",
                 "source_url": "https://example.org/report.pdf", "page": 12,
                 "verification": "announcement_text_checked"}, **changes)


def prepare(tmp_path, monkeypatch, records):
    m = module()
    path = tmp_path / "operating_metrics.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(m, "METRICS_PATH", path)
    return m


def test_exact_company_period_and_signed_disclosed_unit_margin(tmp_path, monkeypatch):
    rows = [record("销售单价（不含税）", 21520), record("单位销售成本", 22375, page=13),
            record("销售数量", 180081, unit="吨"),
            record("单位销售成本", 1, period="2025-06-30"),
            record("销售单价（不含税）", 1, code="sh.600111")]
    m = prepare(tmp_path, monkeypatch, rows)
    result = m.load_operating_disclosure("sh.601899", "2026-06-30")
    assert len(result["records"]) == 3
    assert result["period"] == "2026-06-30"
    assert result["products"] == [{"name": "冶炼产锌", "unit": "元/吨", "price": 21520,
        "cost": 22375, "gross_margin": -855, "scope": "抵销前",
        "source_url": "https://example.org/report.pdf", "price_page": 12, "cost_page": 13}]
    assert m.load_operating_disclosure("sh.601899", "2024-12-31")["records"] == []
    assert m.load_operating_disclosure("sh.601899", None)["products"] == []


@pytest.mark.parametrize("changes", [{"scope": "抵销后"}, {"unit": "元/克"},
    {"commodity": "矿山产铜"}, {"verification": "unverified"},
    {"source_url": "https://example.org/other.pdf"}])
def test_incompatible_or_unverified_pairs_have_warning(tmp_path, monkeypatch, changes):
    m = prepare(tmp_path, monkeypatch, [record("销售单价（不含税）", 100), record("单位销售成本", 50, **changes)])
    result = m.load_operating_disclosure("sh.601899", "2026-06-30")
    assert not result["products"]
    assert result["warnings"]


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True, "bad"])
def test_invalid_cost_cannot_produce_margin(tmp_path, monkeypatch, value):
    m = prepare(tmp_path, monkeypatch, [record("销售单价（不含税）", 100), record("单位销售成本", value)])
    result = m.load_operating_disclosure("sh.601899", "2026-06-30")
    assert not result["products"]
    assert result["warnings"]


def test_identical_duplicates_deduplicate_but_conflicting_values_refuse(tmp_path, monkeypatch):
    price, cost = record("销售单价（不含税）", 100), record("单位销售成本", 50)
    m = prepare(tmp_path, monkeypatch, [price, dict(price), cost])
    assert len(m.load_operating_disclosure("sh.601899", "2026-06-30")["products"]) == 1
    m = prepare(tmp_path, monkeypatch, [price, record("销售单价（不含税）", 101), cost])
    result = m.load_operating_disclosure("sh.601899", "2026-06-30")
    assert not result["products"]
    assert result["warnings"]


def test_missing_or_malformed_file_graceful(tmp_path, monkeypatch):
    m = module()
    path = tmp_path / "missing.json"
    monkeypatch.setattr(m, "METRICS_PATH", path)
    assert not m.load_operating_disclosure("sh.601899", "2026-06-30")["records"]
    path.write_text("{broken", encoding="utf-8")
    assert m.load_operating_disclosure("sh.601899", "2026-06-30")["warnings"]
