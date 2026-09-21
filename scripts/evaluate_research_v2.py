"""Author-known development validation, separately frozen, scored on every turn."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_research import CONTRACT, CLAIMS, digest, dump, now, score_answer

OUTPUT = ROOT / 'output/evaluation_v2'
MODES = ('direct', 'fixed', 'agent')
SOURCE_FILES = ('agent.py', 'prompts.py', 'tools/profit_analysis.py', 'tools/profit_scenarios.py',
                'scripts/evaluate_research.py', 'scripts/evaluate_research_v2.py')


def call(name, **arguments):
    return {'name': name, 'arguments': arguments}


def metric(value, unit='元'):
    return {'value': value, 'unit': unit, 'atol': .02, 'rtol': 1e-6}


def make_tasks():
    from tools.profit_analysis import analyze_profit
    tasks = []
    def turn(question, metrics, calls=(), status='ok', sources=()):
        return {'question': question, 'fixed_calls': list(calls), 'source_ids': list(sources),
                'expected': {'status': status, 'metrics': metrics, 'claims': dict.fromkeys(CLAIMS, False), 'classifications': {}}}
    def financial(name, period, question=None):
        data = analyze_profit(name, period=period)
        assert data['period'] == period and data['statement']['OPERATE_INCOME'] is not None
        return turn(question or f'查询{name}{period}累计报告期营业收入和毛利，保持原报告期，不年化。',
                    {'revenue': metric(data['statement']['OPERATE_INCOME']), 'gross_profit': metric(data['statement']['GROSS_PROFIT'])},
                    [call('get_profit_analysis', query=name, period=period)], sources=[data['source']['url']])
    for index, name in enumerate(('云铝股份', '铜陵有色', '厦门钨业'), 1):
        tasks.append({'id': f'F{index:02}', 'category': 'financial', 'turns': [financial(name, '2025-12-31')]})
    tasks.append({'id': 'C01', 'category': 'cross_period', 'turns': [turn(
        '云铝股份2025-12-31全年与2026-06-30中报营业收入是否可直接相减作为同比变化？报告期长度不同则拒绝计算difference，不年化。',
        {'difference': metric(None)}, [call('get_profit_analysis', query='云铝股份', period=p) for p in ('2025-12-31', '2026-06-30')],
        status='abstain', sources=[analyze_profit('云铝股份', period='2025-12-31')['source']['url']])]})
    scenarios = [
        ('processing', {'processing_fee': 2300, 'raw_price': 24000, 'yield_rate': .92, 'conversion_cost': 650}, 1650 - 24000 * (1 / .92 - 1), '元/吨成品'),
        ('mining', {'price': 80000, 'mining_cost': 43000, 'transport_cost': 1500, 'resource_tax': 3200, 'byproduct_credit': 600}, 32900, '元/吨可售金属'),
        ('recycling', {'product_price': 35000, 'grade': .22, 'recovery': .88, 'service_fee': 120, 'feed_cost': 4800, 'processing_cost': 900, 'environmental_cost': 250}, 946, '元/干吨废料'),
        ('smelting', {'tc': -12, 'rc': .035, 'exchange_rate': 7.2, 'grade': .28, 'recovery': .965, 'payable_fraction': .95, 'conversion_cost': 1600, 'byproduct_credit': 180},
         (-12 + .035 * 2204.6226218488 * .28 * .95) * 7.2 / (.28 * .965) - 1420, '元/吨回收金属'),
    ]
    for index, (model, values, total, unit) in enumerate(scenarios, 1):
        tasks.append({'id': f'S{index:02}', 'category': 'scenario', 'turns': [turn(
            f'按公开{model}模型计算假设经营贡献。参数采用该模型标准单位：{json.dumps(values)}。这些是用户假设，不是公司实测数据。',
            {'contribution': metric(total, unit)}, [call('calculate_profit_scenario', model=model, values=values)], sources=['user:scenario'])]})
    missing = {'price': 52000, 'product_content': .42, 'feed_grade': .12, 'feed_price': 5800, 'conversion_cost': 9500, 'byproduct_credit': 0}
    tasks.append({'id': 'X01', 'category': 'missing', 'turns': [turn(
        f'按refining模型计算贡献。已知标准单位参数{json.dumps(missing)}，回收率未披露，不得默认或估计。',
        {'contribution': metric(None, '元/吨产品')}, [call('calculate_profit_scenario', model='refining', values=missing)], 'abstain', ['user:scenario'])]})
    tasks.append({'id': 'X02', 'category': 'missing', 'turns': [turn(
        '某矿山吨经营贡献为3200元，但销量、税费、期间费用和少数股东比例未知。计算公司归母净利润；无法确定则明确拒绝补齐。',
        {'parent_netprofit': metric(None)}, status='abstain', sources=['user:scenario'])]})
    base = {'price': 90000, 'mining_cost': 48000, 'transport_cost': 2100, 'resource_tax': 4000, 'byproduct_credit': 1100}
    updated = {**base, 'mining_cost': 53000}
    unit = '元/吨可售金属'
    tasks.append({'id': 'T01', 'category': 'multiturn', 'turns': [
        turn(f'建立矿山mining假设，按公开模型标准单位，参数{json.dumps(base)}，给出贡献。', {'contribution': metric(37000, unit)},
             [call('calculate_profit_scenario', model='mining', values=base)], sources=['user:scenario']),
        turn('仅把上一轮mining_cost改为53000，其余保持不变，给出更新后的贡献。', {'contribution': metric(32000, unit)},
             [call('calculate_profit_scenario', model='mining', values=updated)], sources=['user:scenario']),
        turn('分别返回最初贡献original_contribution和更新后贡献updated_contribution，保持原计量单位。',
             {'original_contribution': metric(37000, unit), 'updated_contribution': metric(32000, unit)}, sources=['user:scenario'])]})
    tasks.append({'id': 'T02', 'category': 'multiturn', 'turns': [financial('云铝股份', '2025-12-31'),
        financial('厦门钨业', '2025-12-31', '切换公司为厦门钨业，仍查询2025-12-31累计营业收入和毛利，之后以厦门钨业为当前公司。'),
        financial('厦门钨业', '2026-06-30', '现在查询当前公司的2026-06-30累计营业收入和毛利，保持中报期间，不年化。')]})
    assert len(tasks) == 12 and sum(len(t['turns']) for t in tasks) == 16
    return tasks


def freeze():
    if (OUTPUT / 'freeze.json').exists():
        raise RuntimeError('Existing freeze is immutable')
    from tools import TOOLS, execute_tool
    tasks = make_tasks()
    snapshots = {}
    for name in ('云铝股份', '铜陵有色', '厦门钨业'):
        calls = [call('get_profit_analysis', query=name, period=p) for p in ('2025-12-31', '2026-06-30')]
        calls += [call(tool, query=name) for tool in ('get_profit_analysis', 'get_stock_fundamentals', 'get_company_profile')]
        for item in calls:
            snapshots[json.dumps(item, sort_keys=True, ensure_ascii=False)] = execute_tool(item['name'], item['arguments'])
    schemas = [t for t in TOOLS if t['function']['name'] in ('get_profit_analysis', 'calculate_profit_scenario', 'get_stock_fundamentals', 'get_company_profile')]
    dump(OUTPUT / 'tasks.json', tasks)
    dump(OUTPUT / 'snapshots.json', snapshots)
    dump(OUTPUT / 'schemas.json', schemas)
    files = [ROOT / p for p in SOURCE_FILES] + [OUTPUT / p for p in ('tasks.json', 'snapshots.json', 'schemas.json')]
    dump(OUTPUT / 'freeze.json', {'frozen_at': now(), 'tasks': 12, 'turns_per_mode': 16,
         'manifest': {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in files},
         'protocol': ['Author-known development validation, not blind holdout.',
                      'Every turn scored; a task passes only when all its turns pass.',
                      'Fixed mode receives only current-turn scheduled outputs; no future inputs.',
                      'Agent and fixed share four available public tools and identical cached outputs.',
                      'Direct has no tool observations; this information difference does not isolate planning skill.',
                      'All modes request strict JSON and allow one repair. Agent and fixed use the same limited direct-value conflict detector; direct has no tool values to compare.',
                      'All responses and failures retained; no reruns or tuning after freeze.',
                      'Source score is exact reference-set matching, not semantic citation verification.',
                      'Claims booleans are self-reports. Manual narrative audit is required.',
                      'Not a validation of all production tools, live data retrieval, monetary cost, or universal parameter provenance.']})


def executor_for(snapshots):
    from tools import execute_tool
    def execute(name, arguments):
        if name == 'calculate_profit_scenario':
            return execute_tool(name, arguments)
        key = json.dumps({'name': name, 'arguments': arguments}, sort_keys=True, ensure_ascii=False)
        if key in snapshots:
            return snapshots[key]
        for encoded, output in snapshots.items():
            item = json.loads(encoded)
            if item['name'] != name or {k: v for k, v in arguments.items() if k != 'query'} != {k: v for k, v in item['arguments'].items() if k != 'query'}:
                continue
            try:
                data = json.loads(output)
            except ValueError:
                continue
            code = str(data.get('code') or '')
            if str(arguments.get('query', '')).strip() in (data.get('name'), code, code.split('.')[-1]):
                return output
        return '错误：本次冻结工具环境无该公司或报告期数据，不得填零或使用其他期间替代。'
    return execute


def score_turn(turn, answer):
    result = score_answer(turn, answer)
    result['reference_set_match'] = result.pop('source_supported')
    return result


def verify_freeze():
    meta = json.loads((OUTPUT / 'freeze.json').read_text(encoding='utf-8'))
    for relative, expected in meta['manifest'].items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError('Frozen file changed: ' + relative)
    return meta


def run_case(case, mode):
    import agent
    from config import create_llm_client, load_llm_config
    from prompts import SYSTEM_PROMPT
    verify_freeze()
    snapshots = json.loads((OUTPUT / 'snapshots.json').read_text(encoding='utf-8'))
    schemas = json.loads((OUTPUT / 'schemas.json').read_text(encoding='utf-8'))
    executor = executor_for(snapshots)
    api = create_llm_client().with_options(max_retries=0, timeout=90)
    config = load_llm_config()
    calls, usage, events, records, history = [], [], [], [], []
    def create(**kwargs):
        kwargs['max_tokens'] = 1800
        started = perf_counter()
        record = {'index': len(calls) + 1, 'status': 'started'}
        calls.append(record)
        try:
            response = api.chat.completions.create(**kwargs)
            record['status'] = 'completed'
            # Retain pre-repair responses and actual tool arguments for audit.
            record['message'] = response.choices[0].message.model_dump()
            counts = getattr(response, 'usage', None)
            usage.append({k: getattr(counts, k, None) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
            return response
        except Exception as exc:
            record.update(status='error', error_type=type(exc).__name__)
            raise
        finally:
            record['seconds'] = round(perf_counter() - started, 3)
    wrapped = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    started = perf_counter()
    for index, turn in enumerate(case['turns'], 1):
        prompt = turn['question'] + '\n本轮指标与单位：' + json.dumps({k: v['unit'] for k, v in turn['expected']['metrics'].items()}, ensure_ascii=False) + '\n' + CONTRACT
        before = len(calls)
        turn_started = perf_counter()
        answer, error = '', None
        try:
            if mode == 'agent':
                with patch.object(agent, 'execute_tool', executor), patch.object(agent, 'TOOLS', schemas), patch.object(agent, 'create_llm_client', lambda: wrapped):
                    answer = agent.run_agent(prompt, history=history, max_steps=3, response_format='json_object',
                                             on_event=lambda event: events.append({'turn': index, **event}))
            else:
                outputs, observations = [], []
                if mode == 'fixed':
                    for item in turn['fixed_calls']:
                        output = executor(item['name'], item['arguments'])
                        outputs.append({**item, 'output': output})
                        observations.extend(agent._observations(item['name'], output, ''))
                        events.append({'event': 'fixed_tool_output', 'turn': index, **item, 'output': output})
                messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, *history, {'role': 'user', 'content': prompt + ('\n本轮实际工具输出：' + json.dumps(outputs, ensure_ascii=False) if outputs else '')}]
                for attempt in range(2):
                    response = create(model=config.model, messages=messages, temperature=.2, response_format={'type': 'json_object'})
                    answer = response.choices[0].message.content or ''
                    try:
                        agent._json_object(answer)
                        conflicts = agent._answer_conflicts(answer, observations)
                        if conflicts:
                            raise ValueError('tool_value_conflict')
                        break
                    except ValueError:
                        if attempt:
                            raise
                        events.append({'event': 'baseline_repair', 'turn': index})
                        messages += [{'role': 'assistant', 'content': answer}, {'role': 'user', 'content': '请修复为合法JSON对象；核对数值与实际工具输出一致。只返回JSON。'}]
        except Exception as exc:
            error = type(exc).__name__
        record = {'turn': index, 'question': turn['question'], 'answer': answer, 'error': error,
                  'api_calls': len(calls) - before, 'seconds': round(perf_counter() - turn_started, 3),
                  'score': score_turn(turn, answer)}
        if error:
            record['score']['passed'] = False
            record['score']['errors'].append('execution_error:' + error)
        records.append(record)
        history.extend([{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': answer or '本轮执行失败，未生成可验证结论。'}])
    api.close()
    result = {'task_id': case['id'], 'mode': mode, 'model': config.model, 'finished_at': now(), 'turns': records,
              'passed': all(r['score']['passed'] for r in records), 'events': events, 'requests': calls, 'usage': usage,
              'api_calls': len(calls), 'seconds': round(perf_counter() - started, 3),
              'tokens': sum(u['total_tokens'] or 0 for u in usage), 'cost_estimate': None}
    dump(OUTPUT / 'runs' / f"{case['id']}_{mode}.json", result)
    return result


def summarize():
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((OUTPUT / 'runs').glob('*.json'))]
    summary = {}
    for mode in MODES:
        rows = [r for r in records if r['mode'] == mode]
        turns = [t for r in rows for t in r['turns']]
        summary[mode] = {'tasks': len(rows), 'tasks_passed': sum(r['passed'] for r in rows), 'turns': len(turns),
                         'turns_passed': sum(t['score']['passed'] for t in turns),
                         'numeric_correct': sum(t['score']['numeric_correct'] for t in turns),
                         'numeric_total': sum(t['score']['numeric_total'] for t in turns),
                         'reference_set_match': sum(t['score']['reference_set_match'] for t in turns),
                         'errors': sum(bool(t['error']) for t in turns), 'api_calls': sum(r['api_calls'] for r in rows),
                         'tokens': sum(r['tokens'] for r in rows)}
    dump(OUTPUT / 'summary.json', {'created_at': now(), 'results': summary, 'protocol': verify_freeze()['protocol']})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        print('Frozen 12 tasks, 16 turns per mode.', flush=True)
    if args.run:
        tasks = json.loads((OUTPUT / 'tasks.json').read_text(encoding='utf-8'))
        for case in tasks:
            for mode in MODES:
                if (OUTPUT / 'runs' / f"{case['id']}_{mode}.json").exists():
                    continue
                result = run_case(case, mode)
                print(json.dumps({k: result[k] for k in ('task_id', 'mode', 'passed', 'api_calls', 'seconds')}), flush=True)
        print(json.dumps(summarize(), ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
