import math

import pandas as pd
import pytest

from tools import profit_scenarios as ps


CASES = {
    "mining": ({"price": 100, "mining_cost": 70, "transport_cost": 10, "resource_tax": 5}, 15),
    "smelting": ({"tc": 50, "rc": .05, "exchange_rate": 7, "grade": .25,
                  "recovery": .96, "payable_fraction": .95, "conversion_cost": 2000},
                 (50 + .05 * 2204.6226218488 * .25 * .95) * 7 / (.25 * .96) - 2000),
    "aluminum": ({"price": 20000, "alumina_price": 3000, "alumina_consumption": 1.93,
                  "power_consumption": 13500, "electricity_price": .45, "other_cost": 2500}, 5635),
    "processing": ({"processing_fee": 2000, "raw_price": 10000, "yield_rate": .8,
                    "conversion_cost": 500}, -1000),
    "refining": ({"price": 50000, "product_content": .4, "feed_grade": .1,
                  "recovery": .8, "feed_price": 5000, "conversion_cost": 10000}, 15000),
    "recycling": ({"product_price": 10000, "grade": .5, "recovery": .8,
                   "service_fee": 300, "feed_cost": 2000, "processing_cost": 500,
                   "environmental_cost": 200}, 1600),
    "trading": ({"sales": 100, "purchase": 80, "logistics": 5,
                 "financing_hedging_cost": 20}, -5),
}


@pytest.mark.parametrize("model", CASES)
def test_models_calculate_signed_contribution_and_plotly_waterfall(model):
    inputs, expected = CASES[model]
    result = ps.calculate_scenario(model, inputs)
    assert result["total"] == pytest.approx(expected)
    assert sum(result["values"][:-1]) == pytest.approx(expected)
    assert result["values"][-1] == 0
    assert result["measures"] == ["relative"] * (len(result["labels"]) - 1) + ["total"]
    assert len(result["values"]) == len(result["labels"])
    assert result["unit"] == ps.MODELS[model]["unit"]


def test_break_even_and_optional_byproduct_credit():
    inputs = {**CASES["mining"][0], "price": 85}
    assert ps.calculate_scenario("mining", inputs)["total"] == 0
    assert ps.calculate_scenario("mining", {**inputs, "byproduct_credit": 10})["total"] == 10


@pytest.mark.parametrize("value", [0, -1, 1.01, math.nan, math.inf, True, "bad"])
def test_invalid_recovery_rejected(value):
    with pytest.raises(ValueError, match="回收率"):
        ps.calculate_scenario("refining", {**CASES["refining"][0], "recovery": value})


@pytest.mark.parametrize("model", CASES)
def test_missing_values_never_filled_with_fabricated_costs(model):
    with pytest.raises(ValueError, match="缺少必填参数"):
        ps.calculate_scenario(model, {})


def test_missing_conversion_parameter_and_wrong_units_are_errors():
    values = {**CASES["smelting"][0]}
    del values["grade"]
    with pytest.raises(ValueError, match="品位"):
        ps.calculate_scenario("smelting", values)
    with pytest.raises(ValueError, match="不支持的参数"):
        ps.calculate_scenario("mining", {**CASES["mining"][0], "ore_price": 10})


def test_negative_tc_and_net_hedging_gains_remain_signed():
    assert ps.calculate_scenario("smelting", {**CASES["smelting"][0], "tc": -50})["total"] < 0
    assert ps.calculate_scenario("trading", {**CASES["trading"][0], "financing_hedging_cost": -20})["total"] == 35


def test_overflow_does_not_return_nonfinite_result():
    with pytest.raises(ValueError, match="有限"):
        ps.calculate_scenario("aluminum", {**CASES["aluminum"][0], "alumina_price": 1e308})


def test_registry_axes_and_fields_have_explicit_units():
    assert set(ps.MODELS) == set(CASES)
    for model in ps.MODELS.values():
        keys = [f["key"] for f in model["fields"]]
        assert len(keys) == len(set(keys))
        assert len(model["axes"]) == 2
        assert all(axis in keys for axis in model["axes"])
        assert all(f["label"] and f["unit"] for f in model["fields"])


def test_defaults_only_explicit_assumptions_and_dated_industry_prices(tmp_path, monkeypatch):
    prices = tmp_path / "prices.parquet"
    pd.DataFrame({"date": ["2026-01-02", "2026-01-01", "2099-01-01"],
                  "aluminum": [20000, 19000, 99999], "alumina": [3000, 2900, 99999]}).to_parquet(prices)
    monkeypatch.setattr(ps, "METAL", prices)
    default = ps.scenario_defaults("aluminum")
    assert default["values"]["price"] == 20000
    assert default["values"]["alumina_consumption"] == 1.93
    assert default["statuses"]["price"] == "industry_price"
    assert default["statuses"]["other_cost"] == "assumption"
    assert "2026-01-02" in default["sources"]["price"]
    for name in set(CASES) - {"aluminum"}:
        defaults = ps.scenario_defaults(name)
        for field in ps.MODELS[name]["fields"]:
            assert defaults["values"][field["key"]] == field.get("default")


def test_unavailable_prices_stay_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "METAL", tmp_path / "missing.parquet")
    default = ps.scenario_defaults("aluminum")
    assert default["values"]["price"] is None
    assert default["statuses"]["price"] == "missing"
