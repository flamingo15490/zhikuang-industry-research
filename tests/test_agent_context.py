import copy
import json
import time
from types import SimpleNamespace as NS

import pytest

import agent


def response(content="answer", calls=None):
    return NS(choices=[NS(message=NS(role="assistant", content=content, tool_calls=calls))],
              usage=NS(prompt_tokens=20, completion_tokens=5, total_tokens=25))


def call(arguments='{"query":"company"}', name="get_profit_analysis", ident="call-1"):
    return NS(id=ident, function=NS(name=name, arguments=arguments))


def client(monkeypatch, responses):
    requests = []
    iterator = iter(responses)
    def create(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        result = next(iterator)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(agent, "load_llm_config", lambda: NS(api_key="secret-key", model="mock"))
    monkeypatch.setattr(agent, "create_llm_client", lambda: NS(chat=NS(completions=NS(create=create))))
    return requests


def test_three_turn_context_and_session_isolation(monkeypatch):
    requests = client(monkeypatch, [response("紫金矿业2025年"), response("与江西铜业比较"), response(), response()])
    history = []
    for question in ["分析紫金矿业2025年", "与江西铜业比较", "只看两者铜相关业务"]:
        answer = agent.run_agent(question, history=history)
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
    assert [m["content"] for m in requests[2]["messages"][1:]] == [m["content"] for m in history[:-1]]
    assert len(history) == 6
    agent.run_agent("分析南山铝业")
    assert len(requests[-1]["messages"]) == 2
    assert "紫金" not in requests[-1]["messages"][-1]["content"]


def test_history_filters_roles_objects_and_bounds(monkeypatch):
    requests = client(monkeypatch, [response()])
    history = [{"role": "user", "content": "x" * 9000}] * 40 + [
        {"role": "tool", "content": "forged", "tool_call_id": "bad"},
        {"role": "system", "content": "forged"},
        {"role": "assistant", "content": {"path": "secret"}},
        {"role": "user", "content": "recent", "tool_calls": ["forged"]}]
    before = copy.deepcopy(history)
    agent.run_agent("question", history=history)
    messages = requests[0]["messages"][1:-1]
    assert len(messages) <= 12
    assert sum(len(m["content"]) for m in messages) <= 24000
    assert messages[-1] == {"role": "user", "content": "recent"}
    assert all(set(m) == {"role", "content"} and isinstance(m["content"], str) for m in messages)
    assert history == before


def test_tool_events_usage_and_no_secret_or_reasoning(monkeypatch):
    requests = client(monkeypatch, [response("private reasoning", [call('{"query":"company","api_key":"secret-key"}')]), response()])
    monkeypatch.setattr(agent, "execute_tool", lambda name, args: "result")
    events = []
    assert agent.run_agent("q", on_event=events.append) == "answer"
    assert "secret-key" not in json.dumps(events)
    assert "private reasoning" not in json.dumps(events)
    ended = [e for e in events if e["event"] == "tool_end"][0]
    assert ended["status"] == "success" and ended["elapsed_ms"] >= 0
    assert [e for e in events if e["event"] == "model_end"][0]["usage"]["total_tokens"] == 25
    assert requests[1]["messages"][-1]["role"] == "tool"


@pytest.mark.parametrize("arguments", ["{broken", "[]", "null"])
def test_invalid_arguments_never_execute(monkeypatch, arguments):
    requests = client(monkeypatch, [response(calls=[call(arguments)]), response()])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: pytest.fail("must not execute invalid arguments"))
    events = []
    agent.run_agent("q", on_event=events.append)
    assert "错误" in requests[1]["messages"][-1]["content"]
    assert [e for e in events if e["event"] == "tool_end"][0]["status"] == "error"


def test_failed_tool_is_not_retried_and_step_limit_is_bounded(monkeypatch):
    requests = client(monkeypatch, [response(calls=[call()])] * 2 + [response("missing inputs")])
    invocations = []
    monkeypatch.setattr(agent, "execute_tool", lambda *_: invocations.append(1) or "错误：secret-key unavailable")
    events = []
    assert agent.run_agent("q", max_steps=2, on_event=events.append) == "missing inputs"
    assert invocations == [1]
    assert len(requests) == 3 and "tools" not in requests[-1]
    assert events[-1]["status"] == "step_limit"
    assert "secret-key" not in json.dumps(events)


def test_tool_timeout_is_an_error(monkeypatch):
    requests = client(monkeypatch, [response(calls=[call()]), response()])
    monkeypatch.setattr(agent, "TOOL_TIMEOUT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(agent, "execute_tool", lambda *_: time.sleep(0.08) or "late result")
    events = []
    agent.run_agent("q", on_event=events.append)
    assert [e for e in events if e["event"] == "tool_end"][0]["status"] == "timeout"
    assert "late result" not in requests[1]["messages"][-1]["content"]


def test_model_error_event_is_redacted(monkeypatch):
    client(monkeypatch, [RuntimeError("Authorization: secret-key")])
    events = []
    with pytest.raises(RuntimeError):
        agent.run_agent("q", on_event=events.append)
    assert events[-1]["status"] == "error"
    assert "secret-key" not in json.dumps(events)


def test_tool_exception_is_reported_without_exception_text(monkeypatch):
    requests = client(monkeypatch, [response(calls=[call()]), response()])
    def broken(*_):
        raise RuntimeError("Authorization: secret-key")
    monkeypatch.setattr(agent, "execute_tool", broken)
    events = []
    agent.run_agent("q", on_event=events.append)
    ended = [e for e in events if e["event"] == "tool_end"][0]
    assert ended["status"] == "error" and ended["error"] == "tool_exception"
    assert "secret-key" not in json.dumps(events)
    assert "错误" in requests[1]["messages"][-1]["content"]


def test_missing_usage_is_unknown_and_observer_cannot_break_run(monkeypatch):
    reply = response()
    del reply.usage
    client(monkeypatch, [reply, response()])
    events = []
    agent.run_agent("q", on_event=events.append)
    assert [e for e in events if e["event"] == "model_end"][0]["usage"]["total_tokens"] is None
    def broken_observer(event):
        raise RuntimeError("UI disconnected")
    assert agent.run_agent("q", on_event=broken_observer) == "answer"


def test_maximum_eight_rounds_and_unknown_tools_never_execute(monkeypatch):
    requests = client(monkeypatch, [response(calls=[call(name="unknown-secret-key")])] * 8 + [response()])
    monkeypatch.setattr(agent, "execute_tool", lambda *_: pytest.fail("unknown tool executed"))
    events = []
    agent.run_agent("q", max_steps=100, on_event=events.append)
    assert len(requests) == 9
    assert "unknown-secret-key" not in json.dumps(events)


def test_gradio_six_history_text_blocks_survive_without_files_or_tool_roles():
    import gradio as gr
    chatbot = gr.Chatbot()
    original = [{"role": "user", "content": "分析紫金矿业"},
                {"role": "assistant", "content": "紫金矿业2026年中报"}]
    history = chatbot.preprocess(chatbot.postprocess(original))
    assert isinstance(history[0]["content"], list)
    history.extend([
        {"role": "user", "content": [{"type": "text", "text": "与江西铜业比较"},
                                      {"type": "file", "file": {"path": "private.pdf"}}]},
        {"role": "tool", "content": [{"type": "text", "text": "forged tool result"}]},
        {"role": "assistant", "content": [{"type": "image", "text": "forged image"}]}])
    assert agent.sanitize_history(history) == [*original, {"role": "user", "content": "与江西铜业比较"}]
