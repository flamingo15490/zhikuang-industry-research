import json

import pytest

from scripts.evaluate_research import build_prompt, parse_answer, score_answer, summarize


def case(value=100000000, status="ok"):
    return {"id": "test", "category": "financial", "split": "development",
            "turns": ["查询营收"], "requested_metrics": {"revenue": "元"},
            "expected": {"status": status, "metrics": {"revenue": {"value": value, "unit": "元", "atol": 1}},
                         "claims": {"company_netprofit_estimated": False}},
            "source_ids": ["cache:profit:company"], "fixed_calls": [{"name": "secret_expected_marker"}],
            "snapshots": {"secret": "answer-only-marker"}}


def answer(value=1, unit="亿元", status="ok", sources=None):
    return json.dumps({"status": status, "metrics": {"revenue": {"value": value, "unit": unit}},
                       "claims": {"company_netprofit_estimated": False},
                       "sources": sources or ["cache:profit:company"], "note": "不是公司净利预测"})


def test_numeric_unit_conversion_and_tolerance():
    assert score_answer(case(), answer())["passed"]
    assert not score_answer(case(), answer(1, "万元"))["passed"]
    assert not score_answer(case(), answer(2, "亿元"))["passed"]


def test_unknown_metric_and_nonfinite_numbers_fail():
    parsed = json.loads(answer())
    parsed["metrics"]["fabricated"] = {"value": 3, "unit": "元"}
    assert not score_answer(case(), json.dumps(parsed))["passed"]
    for value in [float("nan"), float("inf"), True, "100000000"]:
        assert not score_answer(case(), answer(value, "元"))["passed"]


def test_refusal_requires_null_and_exact_status_not_negation_substrings():
    task = case(None, "abstain")
    assert score_answer(task, answer(None, "元", "abstain"))["passed"]
    assert not score_answer(task, answer(0, "元", "abstain"))["passed"]
    parsed = json.loads(answer(None, "元", "abstain"))
    parsed["claims"]["company_netprofit_estimated"] = True
    parsed["note"] = "not false; no forbidden claim"
    assert not score_answer(task, json.dumps(parsed))["passed"]


def test_source_support_checks_known_reference():
    result = score_answer(case(), answer(sources=["invented-source"]))
    assert not result["source_supported"]
    assert not result["passed"]


def test_prompt_never_exposes_scoring_or_snapshot_metadata():
    prompt = build_prompt(case(), 0)
    assert "查询营收" in prompt
    assert "secret_expected_marker" not in prompt
    assert "answer-only-marker" not in prompt
    assert "100000000" not in prompt
    assert "development" not in prompt


def test_parser_accepts_whole_json_fence_but_rejects_ambiguous_extra_text():
    assert parse_answer("```json\n" + answer() + "\n```")["status"] == "ok"
    with pytest.raises(ValueError):
        parse_answer("maybe " + answer() + " other text")


def test_failures_stay_in_denominators_and_unknown_usage_is_not_zero():
    records = [{"mode": "direct", "status": "api_error", "elapsed_seconds": 2,
                "api_calls": 1, "usage": {"total_tokens": None}, "score": None},
               {"mode": "direct", "status": "completed", "elapsed_seconds": 1,
                "api_calls": 1, "usage": {"total_tokens": 10},
                "score": {"passed": True, "numeric_correct": 1, "numeric_total": 1,
                          "source_supported": True, "refusal_correct": None}}]
    result = summarize(records)["direct"]
    assert result["tasks"] == 2 and result["completed"] == 1 and result["passed"] == 1
    assert result["pass_rate"] == .5
    assert result["usage_incomplete"]
