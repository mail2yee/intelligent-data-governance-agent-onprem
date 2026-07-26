import json

import pytest

from app.chat import (
    GREETING_REPLY,
    NOT_FOUND_REPLY,
    is_greeting,
    local_rule_match,
    run_chat,
    sse_event,
)

CATALOG = {
    "customer-capacity-allocation": {
        "name": "Specific Customer Capacity Allocation",
        "maturity_level": "Gold",
        "data_quality_score": "99%",
    },
    "move-forecast-summary": {
        "name": "FAB Production Move Forecast Summary",
        "maturity_level": "Gold",
        "data_quality_score": "98%",
    },
}


@pytest.mark.parametrize("msg", ["hi", "Hello", "hey!", "你好", "早安", "hi there", "  hello  "])
def test_is_greeting_true(msg):
    assert is_greeting(msg) is True


@pytest.mark.parametrize("msg", ["我想分析特定客戶投片產能與實際出貨預估", "what is gold maturity", ""])
def test_is_greeting_false(msg):
    assert is_greeting(msg) is False


def test_sse_event_format():
    event = sse_event("step", text="hello")
    assert event.startswith("data: ")
    assert event.endswith("\n\n")
    payload = json.loads(event[len("data: ") :].strip())
    assert payload == {"type": "step", "text": "hello"}


def test_local_rule_match_capacity_zh():
    matched, reply = local_rule_match("我想分析特定客戶產能分配", "zh", CATALOG)
    assert matched == ["customer-capacity-allocation"]
    assert "Specific Customer Capacity Allocation" in reply


def test_local_rule_match_no_match():
    matched, reply = local_rule_match("what is the weather", "en", CATALOG)
    assert matched == []
    assert reply == NOT_FOUND_REPLY["en"]


async def _collect_events(agen):
    events = []
    async for chunk in agen:
        for line in chunk.split("\n\n"):
            line = line.strip()
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_run_chat_greeting_is_instant_no_llm_call(monkeypatch):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("LLM should not be called for a greeting")
        yield  # pragma: no cover

    monkeypatch.setattr("app.chat.stream_chat_completion", _should_not_be_called)

    events = await _collect_events(run_chat("hello", "en", CATALOG))
    assert [e["type"] for e in events] == ["step", "token", "final"]
    assert events[-1]["reply"] == GREETING_REPLY["en"]
    assert events[-1]["matched_products"] == []


async def test_run_chat_llm_success_streams_tokens_and_matches(monkeypatch):
    async def _fake_stream(messages):
        for piece in ["Specific Customer Capacity Allocation", " is a great match."]:
            yield piece

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake_stream)

    events = await _collect_events(run_chat("capacity please", "en", CATALOG))
    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) == 2  # streamed progressively, not one blob
    final = events[-1]
    assert final["type"] == "final"
    assert "customer-capacity-allocation" in final["matched_products"]


async def test_run_chat_llm_failure_falls_back_to_local_match(monkeypatch):
    async def _broken_stream(messages):
        raise ConnectionError("no route to host")
        yield  # pragma: no cover

    monkeypatch.setattr("app.chat.stream_chat_completion", _broken_stream)

    events = await _collect_events(run_chat("我想分析特定客戶產能分配", "zh", CATALOG))
    final = events[-1]
    assert final["matched_products"] == ["customer-capacity-allocation"]
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("降級" in t for t in step_texts)
