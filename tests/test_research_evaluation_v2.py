import json

from scripts import evaluate_research_v2 as evaluation
from tools.profit_scenarios import calculate_scenario


def test_new_development_tasks_score_every_turn_and_no_future_fixed_inputs():
    tasks = evaluation.make_tasks()
    assert len(tasks) == 12
    assert sum(len(t['turns']) for t in tasks) == 16
    task = next(t for t in tasks if t['id'] == 'T01')
    assert task['turns'][0]['fixed_calls'][0]['arguments']['values']['mining_cost'] == 48000
    assert task['turns'][1]['fixed_calls'][0]['arguments']['values']['mining_cost'] == 53000
    assert task['turns'][2]['fixed_calls'] == []
    for task in tasks:
        for turn in task['turns']:
            answer = {**turn['expected'], 'sources': turn['source_ids'], 'note': ''}
            assert evaluation.score_turn(turn, json.dumps(answer))['passed']


def test_independent_scenario_expected_values_match_public_tool():
    for task in evaluation.make_tasks():
        if task['category'] != 'scenario':
            continue
        turn = task['turns'][0]
        actual = calculate_scenario(**turn['fixed_calls'][0]['arguments'])
        expected = turn['expected']['metrics']['contribution']
        assert abs(actual['total'] - expected['value']) < .0001
        assert actual['unit'] == expected['unit']


def test_snapshot_alias_preserves_requested_period():
    item = evaluation.call('get_profit_analysis', query='云铝股份', period='2025-12-31')
    output = json.dumps({'name': '云铝股份', 'code': 'sz.000807'})
    execute = evaluation.executor_for({json.dumps(item, sort_keys=True, ensure_ascii=False): output})
    assert execute('get_profit_analysis', {'query': '000807', 'period': '2025-12-31'}) == output
    assert execute('get_profit_analysis', {'query': '000807', 'period': '2026-06-30'}).startswith('错误')


def test_refusal_and_wrong_intermediate_value_are_not_passes():
    task = next(t for t in evaluation.make_tasks() if t['id'] == 'T01')
    turn = task['turns'][0]
    answer = {**turn['expected'], 'metrics': {'contribution': {'value': 35000, 'unit': '元/吨可售金属'}}, 'sources': ['user:scenario']}
    assert not evaluation.score_turn(turn, json.dumps(answer))['passed']
