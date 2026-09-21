"""ReAct 智能体主循环：思考 → 调用工具 → 观察 → 再思考，直到产出最终回答。"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from html import escape
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from time import perf_counter

from config import create_llm_client, load_llm_config
from prompts import FINAL_JSON_PROMPT, SYSTEM_PROMPT, TOOL_SELECTION_PROMPT
from tools import TOOLS, execute_tool


HISTORY_MAX_MESSAGES = 12
HISTORY_MAX_CHARS = 24000
TOOL_TIMEOUT_SECONDS = 45.0
TOOL_RESULT_MAX_CHARS = 16000
_TOOL_WORKERS = BoundedSemaphore(4)
METRIC_LABELS = {'revenue': '营业收入', 'operating_cost': '营业成本', 'gross_profit': '毛利',
                 'net_profit': '净利润', 'parent_netprofit': '归母净利润', 'contribution': '经营贡献'}


def _json_object(text):
    def reject_constant(value):
        raise ValueError('nonfinite JSON')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    result = json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    # Also rejects numeric overflow such as 1e999, which parse_constant does not see.
    json.dumps(result, allow_nan=False)
    return result


def _redacted(text, secret=''):
    text = str(text)
    if secret:
        text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)(bearer\s+|sk-)[\w.\-]+', '[redacted]', text)
    return re.sub(r'''(?i)(api[_-]?key|token|password|authorization)["']?\s*[:=]\s*["']?[^\s"',;}]+''', '[redacted]', text)


def _error_summary(text, secret=''):
    text = _redacted(text, secret)
    text = re.sub(r'https?://\S+', '[redacted-url]', text)
    text = re.sub(r'(?i)[a-z]:[\\/]+Users[\\/]+[^\s\"\']+|/(?:Users|home)/[^\s\"\']+', '[local-path]', text)
    return text[:300]


def _preferred_tools():
    order = {'get_profit_analysis': 0, 'calculate_profit_scenario': 1}
    return sorted(TOOLS, key=lambda tool: order.get(tool['function']['name'], 2))


def sanitize_history(history: list[dict] | None) -> list[dict]:
    """Copy recent text only; callers cannot inject system or tool envelopes."""
    result = []
    remaining = HISTORY_MAX_CHARS
    for item in reversed(history or []):
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, list):
            content = "\n".join(block["text"] for block in content
                                if isinstance(block, dict) and block.get("type") == "text"
                                and isinstance(block.get("text"), str))
        if not isinstance(content, str) or not content.strip():
            continue
        result.append({"role": item["role"], "content": content[:min(6000, remaining)]})
        remaining -= len(result[-1]["content"])
        if len(result) >= HISTORY_MAX_MESSAGES or remaining <= 0:
            break
    return list(reversed(result))


def _safe_arguments(args: dict, secret: str) -> dict:
    # Only schema-declared research inputs may appear in UI or evaluation logs.
    allowed = {key for tool in TOOLS for key in
               tool["function"].get("parameters", {}).get("properties", {})}
    result = {}
    for key, value in args.items():
        if key not in allowed or re.search(r"key|token|password|secret|auth", key, re.I):
            continue
        if isinstance(value, str):
            result[key] = _redacted(value, secret)[:200]
        elif isinstance(value, dict):
            def numbers(items, depth=0):
                clean = {}
                if depth >= 3:
                    return clean
                for name, number in list(items.items())[:32]:
                    if not isinstance(name, str) or re.search(r'key|token|password|secret|auth', name, re.I):
                        continue
                    if isinstance(number, dict):
                        clean[name[:80]] = numbers(number, depth + 1)
                    elif not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number):
                        clean[name[:80]] = number
                return clean
            result[key] = numbers(value)
        elif value is None or isinstance(value, (bool, int)) or isinstance(value, float) and math.isfinite(value):
            result[key] = value
    return result


def _tool_result(name: str, args: dict, secret='') -> tuple[str, str, str | None]:
    if not _TOOL_WORKERS.acquire(blocking=False):
        return "错误：取数资源繁忙，所需输入仍缺失。", "error", "tool_capacity"
    results = Queue(maxsize=1)
    def work():
        try:
            result = execute_tool(name, args)
            if not isinstance(result, str):
                results.put(("错误：工具返回格式无效。", "error", "invalid_result"))
            elif result.lstrip().startswith(("错误", "Error", "error")):
                results.put((_error_summary(result, secret), "error", "tool_failed"))
            elif len(result) > TOOL_RESULT_MAX_CHARS:
                results.put(("错误：工具结果超过上下文上限，请缩小查询范围；未截断JSON冒充完整结果。", "error", "result_too_large"))
            else:
                results.put((result, "success", None))
        except Exception as exc:
            results.put((_error_summary(f"错误：工具执行失败 {type(exc).__name__}: {exc}", secret), "error", "tool_exception"))
        finally:
            _TOOL_WORKERS.release()
    # Timed-out read-only work may finish later; concurrency remains bounded.
    Thread(target=work, daemon=True).start()
    try:
        return results.get(timeout=TOOL_TIMEOUT_SECONDS)
    except Empty:
        return "错误：工具取数超时，所需输入仍缺失。", "timeout", "tool_timeout"


def _observations(name, text, secret):
    try:
        data = _json_object(text)
    except (ValueError, TypeError):
        return []
    records = []
    if name == 'get_profit_analysis' and data.get('code') and data.get('period'):
        metrics = data.get('financial_metrics')
        if not isinstance(metrics, dict):
            return []
        for key, metric in metrics.items():
            if key not in METRIC_LABELS or not isinstance(metric, dict) or metric.get('unit') != '元':
                continue
            value = metric.get('value')
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                continue
            records.append(dict(tool=name, code=data['code'], name=data.get('name') or data['code'],
                                period=data['period'], metric=key, value=value, unit='元',
                                origin=metric.get('origin'), source=(data.get('source') or {}).get('url')))
    elif name == 'calculate_profit_scenario' and data.get('status') == 'scenario':
        value = data.get('total')
        if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and isinstance(data.get('unit'), str):
            records.append(dict(tool=name, code=None, name=data.get('model'), period=None, metric='contribution',
                                value=value, unit=data['unit'], origin='scenario', source=None))
    return [{key: _redacted(value, secret) if isinstance(value, str) else value for key, value in record.items()}
            for record in records]


def _answer_conflicts(text, records):
    """Check only unambiguous direct metrics, never arbitrary prose or comparisons."""
    by_metric = {}
    for record in records:
        by_metric.setdefault(record['metric'], []).append(record)
    direct = {key: values[0] for key, values in by_metric.items() if len(values) == 1 and values[0]['value'] is not None}
    conflicts = []
    factors = {'元': 1., '万元': 10000., '亿元': 100000000.}
    def financial_binding(record, key, context, answer=None, exact_end=False):
        if record['tool'] != 'get_profit_analysis':
            return True
        # Unscoped prose, hypothetical numbers, and comparisons cannot establish identity.
        if not isinstance(context, str) or re.search(r'假设|如果|假如|预计|预测|目标|计划|例如|对比|比较|分别', context):
            return False
        if answer and answer.get('period') == record['period'] and (
                answer.get('code') == record['code'] or answer.get('name') == record['name']):
            return True
        identity = '(?:' + re.escape(record['name']) + '|' + re.escape(record['code']) + ')'
        binding = identity + r'\s*' + re.escape(record['period']) + r'\s*(?:累计报告期|累计|中报|全年)?\s*' + re.escape(METRIC_LABELS[key])
        if exact_end:
            return bool(re.search(binding + '$', context))
        return context.count(METRIC_LABELS[key]) == 1 and bool(re.search(binding, context))
    def check(key, value, unit, where, context='', answer=None):
        record = direct.get(key)
        if record is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return
        if not financial_binding(record, key, context, answer, exact_end=where == 'note'):
            return
        if unit == record['unit']:
            converted = value
        elif unit in factors and record['unit'] in factors:
            converted = value * factors[unit] / factors[record['unit']]
        else:
            return
        tolerance = 1e-4 if where == 'note' else 1e-6
        if not math.isclose(converted, record['value'], rel_tol=tolerance, abs_tol=.02):
            conflicts.append({'metric': key, 'where': where, 'reported_value': value, 'reported_unit': unit,
                              'tool_value': record['value'], 'tool_unit': record['unit']})
    try:
        answer = _json_object(text)
    except (ValueError, TypeError):
        answer = {}
    metrics = answer.get('metrics', {})
    if isinstance(metrics, dict):
        for key, value in metrics.items():
            if isinstance(value, dict):
                check(key, value.get('value'), value.get('unit'), 'metrics', answer.get('note', ''), answer)
    prose = answer.get('note', '') if answer else text
    if isinstance(prose, str):
        number = r'([+\-−]?\d[\d,]*(?:\.\d+)?(?:[eE][+\-]?\d+)?)'
        for key, record in direct.items():
            if key == 'net_profit' and 'parent_netprofit' in direct:
                label = r'(?<!归母)净利润'
            else:
                label = re.escape(METRIC_LABELS[key]) + (r'(?!率)' if key == 'gross_profit' else '')
            unit = r'(亿元|万元|元)(?!/)' if record['unit'] == '元' else '(' + re.escape(record['unit']) + ')'
            pattern = label + r'\s*(?:为|是|[:：=])?\s*' + number + r'\s*' + unit
            for segment in re.split(r'[。；;\n]', prose):
                for match in re.finditer(pattern, segment):
                    binding_context = segment[:match.start()] + METRIC_LABELS[key]
                    check(key, float(match[1].replace(',', '').replace('−', '-')), match[2], 'note', binding_context)
    return conflicts


def _observation_table(records):
    def cell(value):
        return escape(str(value or '')).replace('|', '\\|').replace('\n', ' ')
    lines = ['\n\n### 工具原始结果', '以下数值直接取自本轮成功工具；模型叙述未经逐句核验。',
             '| 对象 | 报告期 | 指标 | 原始数值 | 单位 | 性质 |', '| --- | --- | --- | ---: | --- | --- |']
    origins = {'reported': '财报值', 'derived': '确定性推导', 'scenario': '假设经营贡献，非公司归母净利润'}
    for record in records:
        value = record['value']
        number = '缺失' if value is None else format(Decimal(str(value)), ',f')
        if '.' in number:
            number = number.rstrip('0').rstrip('.')
        lines.append('| ' + ' | '.join([cell(record['name']), cell(record['period'] or '参数情景（来源未逐项核验）'),
                      METRIC_LABELS[record['metric']], number, cell(record['unit']), origins.get(record['origin'], '未分类')]) + ' |')
    return '\n'.join(lines)


def run_agent(question: str, *, history: list[dict] | None = None,
              max_steps: int = 8, on_event=None, response_format: str = 'text') -> str:
    """Run with bounded text history and observable events, never reasoning traces.

    At most eight tool rounds plus one tool-free final summary are requested.
    Model usage reports provider fields; absent counts stay None, not zero.
    Explicit json_object mode formats after selection, then permits one repair.
    """
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    max_steps = min(max_steps, 8)
    if response_format not in ('text', 'json_object'):
        raise ValueError('response_format must be text or json_object')
    cfg = load_llm_config()
    if not cfg.api_key:
        raise RuntimeError("未配置 LLM_API_KEY：请把 .env.example 复制为 .env 并填入 key")

    client = create_llm_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                *sanitize_history(history), {"role": "user", "content": question}]
    messages[0]['content'] += '\n' + TOOL_SELECTION_PROMPT
    started = perf_counter()
    failed_calls = set()
    tool_names = {tool["function"]["name"] for tool in TOOLS}
    observations = []

    def emit(event, **fields):
        if on_event is not None:
            try:
                on_event({"event": event, **fields})
            except Exception:
                pass  # An unavailable observer must not invalidate research.

    def complete(step, *, final=False):
        began = perf_counter()
        phase = 'final_format' if final else 'tool_selection'
        emit("model_start", step=step, phase=phase, status="running", model=cfg.model)
        options = {} if final else {"tools": _preferred_tools(), "tool_choice": "auto"}
        if final and response_format == 'json_object':
            options['response_format'] = {'type': 'json_object'}
        try:
            resp = client.chat.completions.create(model=cfg.model, messages=messages,
                                                  temperature=0.2, **options)
            msg = resp.choices[0].message
        except Exception:
            emit("model_end", step=step, phase=phase, status="error", model=cfg.model,
                 elapsed_ms=round((perf_counter() - began) * 1000, 2), error="model_request_failed")
            raise
        usage = getattr(resp, "usage", None)
        counts = {key: getattr(usage, key, None) for key in
                  ("prompt_tokens", "completion_tokens", "total_tokens")}
        emit("model_end", step=step, phase=phase, status="success", model=cfg.model,
             elapsed_ms=round((perf_counter() - began) * 1000, 2), usage=counts)
        return msg

    def finish(text, step, run_status):
        text = text or '(模型未返回内容)'
        for attempt in range(2 if response_format == 'json_object' else 1):
            conflicts = _answer_conflicts(text, observations)
            invalid = False
            unverified = []
            if response_format == 'json_object':
                try:
                    parsed = _json_object(text)
                    metrics = parsed.get('metrics')
                    contribution = metrics.get('contribution') if isinstance(metrics, dict) else None
                    if (isinstance(contribution, dict) and contribution.get('value') is not None
                            and not any(r['tool'] == 'calculate_profit_scenario' for r in observations)):
                        unverified = ['contribution']
                except (ValueError, TypeError):
                    invalid = True
            if conflicts or invalid or unverified:
                emit('response_validation', status='invalid_json' if invalid else 'unverified_metric' if unverified else 'conflict', conflicts=conflicts,
                     unverified_metrics=unverified,
                     scope='unambiguous_direct_tool_metrics_only', attempt=attempt + 1)
            if response_format != 'json_object':
                if conflicts:
                    text += '\n\n> 检测到模型数值与工具结果不一致；上方叙述未自动纠正，请核对下方原始结果。'
                if observations:
                    text += _observation_table(observations)
                break
            if not invalid and not conflicts and not unverified:
                text = json.dumps(parsed, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                break
            if attempt == 1:
                emit('run_end', status='error', error='structured_output_validation_failed')
                raise ValueError('JSON输出在一次修复后仍无效、缺少工具证据或与工具数值冲突。')
            if messages[-1].get('role') != 'assistant' or messages[-1].get('content') != text:
                messages.append({'role': 'assistant', 'content': text})
            messages.append({'role': 'user', 'content': '仅修复输出契约：返回有效JSON对象，不要额外文字。'
                             '数值只能取自已经成功的工具结果或用户明确输入；保留缺失，不编造新事实。'
                             'unverified_metrics中的经营贡献未取得实际计算器观测，必须置null并说明未验证，不能沿用助手草稿。'
                             '已检测问题：' + json.dumps({'invalid_json': invalid, 'conflicts': conflicts,
                                                       'unverified_metrics': unverified}, ensure_ascii=False)})
            text = complete(step + 1, final=True).content or ''
        emit('run_end', status=run_status, elapsed_ms=round((perf_counter() - started) * 1000, 2))
        return text

    for step in range(1, max_steps + 1):
        msg = complete(step)

        # 记录 assistant 消息（可能带 tool_calls）
        assistant: dict = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
            if response_format == 'json_object':
                messages.append({'role': 'system', 'content': FINAL_JSON_PROMPT})
                msg = complete(step + 1, final=True)
                return finish(msg.content, step + 1, 'success')
            return finish(msg.content, step, 'success')

        for index, tc in enumerate(msg.tool_calls):
            name = tc.function.name
            began = perf_counter()
            args = {}
            error = None
            try:
                args = _json_object(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
                error = "invalid_arguments"
            signature = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            safe_args = _safe_arguments(args, cfg.api_key)
            safe_name = name if name in tool_names else "unknown_tool"
            emit("tool_start", tool=safe_name, arguments=safe_args, step=step, status="running")
            if name not in tool_names:
                error = "unknown_tool"
            elif index >= 8:
                error = "tool_limit"
            elif signature in failed_calls:
                error = "previous_failure"
            if error:
                result, status = "错误：工具未执行（" + error + "），所需输入仍缺失。", "error"
            else:
                result, status, error = _tool_result(name, args, cfg.api_key)
            if status != "success":
                failed_calls.add(signature)
            emit("tool_end", tool=safe_name, arguments=safe_args, step=step, status=status,
                 elapsed_ms=round((perf_counter() - began) * 1000, 2), error=error,
                 error_summary=result if status != 'success' else None, evidence_ids=[])
            if status == 'success':
                records = _observations(name, result, cfg.api_key)
                observations.extend(records)
                if records:
                    emit('tool_observation', tool=safe_name, step=step, status='observed', records=records,
                         scope='tool_output_only_not_full_answer_audit')
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    # 达到最大步数仍未结束：要求模型基于已有信息强制总结
    messages.append({"role": "user", "content": "已达到取数轮次上限。请仅基于成功取得的信息总结，明确列出失败工具对应的缺失输入，不能编造结论或继续调用工具。"})
    if response_format == 'json_object':
        messages.append({'role': 'system', 'content': FINAL_JSON_PROMPT})
    msg = complete(max_steps + 1, final=True)
    return finish(msg.content, max_steps + 1, 'step_limit')
