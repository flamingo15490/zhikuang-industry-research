import copy
import json
from types import SimpleNamespace as NS

import pytest

import agent
from tools.profit_analysis import format_profit_summary


def response(content=None, calls=None):
    return NS(choices=[NS(message=NS(role="assistant", content=content, tool_calls=calls))], usage=None)


def tool_call(name, args, ident="one"):
    return NS(id=ident, function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))


def fake_client(monkeypatch, replies):
    captured = []
    iterator = iter(replies)
    def create(**kwargs):
        captured.append(copy.deepcopy(kwargs))
        return next(iterator)
    monkeypatch.setattr(agent, "load_llm_config", lambda: NS(api_key="secret-key", model="mock"))
    monkeypatch.setattr(agent, "create_llm_client", lambda: NS(chat=NS(completions=NS(create=create))))
    return captured


def financial_result(revenue=194178458630):
    return json.dumps({"name": "Example", "code": "sh.600001", "period": "2026-06-30",
                       "financial_metrics": {"revenue": {"value": revenue, "unit": "元", "origin": "reported"}},
                       "source": {"url": "https://example.org/statement"}}, ensure_ascii=False)


def scenario_result(total=1100):
    return json.dumps({"model": "recycling", "status": "scenario", "total": total,
                       "unit": "元/干吨废料", "inputs": {"product_price": 20000, "grade": .4},
                       "warning": "假设经营贡献，非公司归母净利润。"}, ensure_ascii=False)


def test_profit_summary_preserves_raw_yuan_and_missing():
    result = json.loads(format_profit_summary({"statement": {"OPERATE_INCOME": 194178458630,
                                                           "GROSS_PROFIT": 73297002903, "PARENT_NETPROFIT": None}}))
    assert result["financial_metrics"]["revenue"] == {"value": 194178458630, "unit": "元", "origin": "reported"}
    assert result["financial_metrics"]["gross_profit"]["origin"] == "derived"
    assert result["financial_metrics"]["parent_netprofit"]["value"] is None


def test_period_is_forwarded_to_actual_profit_engine(monkeypatch):
    import tools.profit_analysis as module
    calls = []
    monkeypatch.setattr(module, "analyze_profit", lambda query, period=None: calls.append((query, period)) or {})
    module.get_profit_analysis("Example", period="2025-12-31")
    assert calls == [("Example", "2025-12-31")]


def test_preferred_tool_order_does_not_force_or_add_model_calls(monkeypatch):
    requests = fake_client(monkeypatch, [response("请明确公司与报告期。")])
    answer = agent.run_agent("查一下净利润")
    assert answer == "请明确公司与报告期。"
    assert len(requests) == 1 and requests[0]["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in requests[0]["tools"][:2]] == ["get_profit_analysis", "calculate_profit_scenario"]


def test_natural_answer_appends_actual_raw_values_and_flags_conflict(monkeypatch):
    fake_client(monkeypatch, [response(calls=[tool_call("get_profit_analysis", {"query": "Example"})]), response("Example 2026-06-30营业收入为194.17845863亿元。")])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: financial_result())
    events = []
    answer = agent.run_agent("查财报营业收入", on_event=events.append)
    assert "194,178,458,630" in answer and "2026-06-30" in answer
    assert "不一致" in answer and "未经逐句核验" in answer
    assert any(event["event"] == "response_validation" and event["status"] == "conflict" for event in events)


def test_plain_scenario_answer_flags_metrics_note_disagreement(monkeypatch):
    wrong = json.dumps({"metrics": {"contribution": {"value": 6200, "unit": "元/干吨废料"}},
                        "note": "经营贡献为1100元/干吨废料。"}, ensure_ascii=False)
    fake_client(monkeypatch, [response(calls=[tool_call("calculate_profit_scenario", {"model": "recycling", "values": {}})]), response(wrong)])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: scenario_result())
    answer = agent.run_agent("计算用户情景")
    assert "不一致" in answer and "1,100" in answer


def test_json_mode_repairs_once_and_does_not_append_markdown(monkeypatch):
    requests = fake_client(monkeypatch, [response('研究完成'), response("preface {\"status\":\"ok\"}"), response('{"status":"ok"}')])
    assert agent.run_agent("返回JSON", response_format="json_object") == '{"status":"ok"}'
    assert len(requests) == 3 and 'response_format' not in requests[0]
    assert all(r['response_format'] == {'type': 'json_object'} and 'tools' not in r for r in requests[1:])
    assert "tools" not in requests[-1]


@pytest.mark.parametrize("bad", ['{"x":NaN}', '{"x":1,"x":2}', '{"x":1e999}', '[]'])
def test_json_validation_fails_closed_after_one_repair(monkeypatch, bad):
    requests = fake_client(monkeypatch, [response('研究完成'), response(bad), response(bad)])
    with pytest.raises(ValueError, match="JSON"):
        agent.run_agent("返回JSON", response_format="json_object")
    assert len(requests) == 3


def test_json_numeric_conflict_is_repaired_from_observed_tool_value(monkeypatch):
    wrong = '{"metrics":{"contribution":{"value":6200,"unit":"元/干吨废料"}}}'
    right = '{"metrics":{"contribution":{"value":1100,"unit":"元/干吨废料"}}}'
    requests = fake_client(monkeypatch, [response(calls=[tool_call("calculate_profit_scenario", {"model": "recycling", "values": {}})]), response('研究完成'), response(wrong), response(right)])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: scenario_result())
    result = agent.run_agent("给出情景贡献JSON", response_format="json_object")
    assert json.loads(result)["metrics"]["contribution"]["value"] == 1100
    assert len(requests) == 4


def test_error_details_survive_redaction_and_missing_args_are_not_invented(monkeypatch):
    requests = fake_client(monkeypatch, [response(calls=[tool_call("calculate_profit_scenario", {"model": "processing", "values": {"processing_fee": 2000}})]), response("缺少成材率，无法计算。")])
    calls = []
    def execute(name, args):
        calls.append(args)
        return "错误：缺少必填参数：成材率；Authorization: secret-key https://private.example/token"
    monkeypatch.setattr(agent, "execute_tool", execute)
    events = []
    answer = agent.run_agent("只有加工费2000，其他数据缺失。", on_event=events.append)
    assert calls[0]["values"] == {"processing_fee": 2000}
    tool_message = requests[1]["messages"][-1]["content"]
    assert "成材率" in tool_message and "secret-key" not in tool_message
    assert "成材率" in json.dumps(events, ensure_ascii=False)
    assert "private.example" not in json.dumps(events)
    assert "工具原始结果" not in answer


def test_nested_numeric_inputs_are_observable_but_secrets_are_not(monkeypatch):
    fake_client(monkeypatch, [response(calls=[tool_call("calculate_profit_scenario", {"model": "mining", "values": {"price": 10, "mining_cost": 3, "api_key": "secret-key"}})]), response("回答")])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: "错误：测试参数不全")
    events = []
    agent.run_agent("使用给定参数", on_event=events.append)
    trace = next(event for event in events if event["event"] == "tool_start")
    assert trace["arguments"]["values"] == {"price": 10, "mining_cost": 3}
    assert "secret-key" not in json.dumps(events)


def test_multiple_observations_are_not_misrepresented_as_unambiguous():
    records = agent._observations('get_profit_analysis', financial_result(100), '')
    records += agent._observations('get_profit_analysis', financial_result(200), '')
    assert agent._answer_conflicts('营业收入为150元。', records) == []


def test_correct_rounded_narrative_and_missing_tool_results():
    records = agent._observations('get_profit_analysis', financial_result(60042935758.93), '')
    assert agent._answer_conflicts('Example 2026-06-30营业收入600.43亿元。', records) == []
    assert agent._observations('get_profit_analysis', '错误：缺少期间', '') == []


def test_json_conflict_remaining_after_repair_fails(monkeypatch):
    wrong = '{"metrics":{"contribution":{"value":6200,"unit":"元/干吨废料"}}}'
    fake_client(monkeypatch, [response(calls=[tool_call('calculate_profit_scenario', {'model': 'recycling', 'values': {}})]), response('研究完成'), response(wrong), response(wrong)])
    monkeypatch.setattr(agent, 'execute_tool', lambda *_: scenario_result())
    with pytest.raises(ValueError):
        agent.run_agent('给出情景贡献JSON', response_format='json_object')


def test_oversized_tool_result_is_explicit_error(monkeypatch):
    monkeypatch.setattr(agent, 'execute_tool', lambda *_: '{"data":"' + 'x' * agent.TOOL_RESULT_MAX_CHARS + '"}')
    text, status, error = agent._tool_result('get_profit_analysis', {'query': 'Example'})
    assert status == 'error' and error == 'result_too_large'
    assert '未截断JSON' in text


@pytest.mark.parametrize('note', ['乙公司营业收入200元。', '以下仅为假设：营业收入200元。',
                                'Example 2025-12-31营业收入200元。', '营业收入200元。',
                                'Example 2026-06-30假设营业收入200元。',
                                'Example 2026-06-30已查到，乙公司营业收入200元。'])
def test_financial_conflict_requires_matching_entity_period_and_actual_fact(note):
    records = agent._observations('get_profit_analysis', financial_result(100), '')
    assert agent._answer_conflicts(note, records) == []
    text = json.dumps({'metrics': {'revenue': {'value': 200, 'unit': '元'}}, 'note': note}, ensure_ascii=False)
    assert agent._answer_conflicts(text, records) == []


def test_bound_financial_metrics_and_note_conflicts_remain_detectable():
    records = agent._observations('get_profit_analysis', financial_result(100), '')
    text = json.dumps({'metrics': {'revenue': {'value': 200, 'unit': '元'}},
                       'note': 'Example 2026-06-30营业收入200元。'}, ensure_ascii=False)
    assert {c['where'] for c in agent._answer_conflicts(text, records)} == {'metrics', 'note'}


def test_scenario_table_does_not_claim_parameter_provenance():
    table = agent._observation_table(agent._observations('calculate_profit_scenario', scenario_result(), ''))
    assert '来源未逐项核验' in table
    assert '用户参数情景' not in table


def test_other_entity_in_same_sentence_is_not_bound_to_earlier_entity():
    records = agent._observations('get_profit_analysis', financial_result(100), '')
    note = 'Example 2026-06-30营业收入100元，乙公司营业收入200元。'
    assert agent._answer_conflicts(note, records) == []


def test_json_selection_and_formatting_are_separate_with_actual_calculator(monkeypatch):
    values = {'price': 80000, 'mining_cost': 43000, 'transport_cost': 1500,
              'resource_tax': 3200, 'byproduct_credit': 600}
    final = '{"metrics":{"contribution":{"value":32900,"unit":"元/吨可售金属"}}}'
    requests = fake_client(monkeypatch, [response(calls=[tool_call('calculate_profit_scenario', {'model': 'mining', 'values': values})]),
                                        response('已完成计算'), response(final)])
    events = []
    assert json.loads(agent.run_agent('使用给定mining参数返回JSON', response_format='json_object', on_event=events.append))['metrics']['contribution']['value'] == 32900
    assert all('response_format' not in r and r['tool_choice'] == 'auto' for r in requests[:2])
    assert 'tools' not in requests[2] and requests[2]['response_format'] == {'type': 'json_object'}
    actual = json.loads(next(m['content'] for m in requests[2]['messages'] if m['role'] == 'tool'))
    assert actual['total'] == 32900 and actual['inputs'] == values
    assert [e['phase'] for e in events if e['event'] == 'model_start'] == ['tool_selection', 'tool_selection', 'final_format']


def test_json_step_limit_formats_once_without_extra_selection(monkeypatch):
    requests = fake_client(monkeypatch, [response(calls=[tool_call('calculate_profit_scenario', {'model': 'mining', 'values': {}})]), response('{"status":"abstain"}')])
    assert agent.run_agent('参数缺失', max_steps=1, response_format='json_object') == '{"status":"abstain"}'
    assert len(requests) == 2 and 'response_format' not in requests[0] and 'tools' not in requests[1]


def test_json_contribution_without_observed_calculator_requires_null(monkeypatch):
    unsupported = '{"metrics":{"contribution":{"value":32900,"unit":"元/吨可售金属"}}}'
    abstain = '{"status":"abstain","metrics":{"contribution":{"value":null,"unit":"元/吨可售金属"}}}'
    requests = fake_client(monkeypatch, [response('未经工具计算'), response(unsupported), response(abstain)])
    events = []
    result = agent.run_agent('计算情景JSON', response_format='json_object', on_event=events.append)
    assert json.loads(result)['metrics']['contribution']['value'] is None
    assert len(requests) == 3 and all('tools' not in r for r in requests[1:])
    assert any(e['event'] == 'response_validation' and e['status'] == 'unverified_metric' for e in events)


def test_json_unobserved_contribution_cannot_survive_repair(monkeypatch):
    unsupported = '{"metrics":{"contribution":{"value":32900,"unit":"元/吨可售金属"}}}'
    fake_client(monkeypatch, [response('草稿'), response(unsupported), response(unsupported)])
    with pytest.raises(ValueError, match='JSON'):
        agent.run_agent('计算情景JSON', response_format='json_object')
