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


async def _noop_sync(catalog):
    return None


def _fake_stream_by_prompt(sql_reply, prose_reply="Some prose reply."):
    """Returns a fake stream_chat_completion that replies differently to
    the SQL-generation prompt (build_sql_prompt's "Write ONE SQL" marker)
    vs. the original prose-reply prompt, since run_chat now calls
    stream_chat_completion twice per successful turn."""

    async def _fake(messages, model=None):
        prompt = messages[0]["content"]
        if "Write ONE SQL" in prompt:
            yield sql_reply
        else:
            yield prose_reply

    return _fake


async def test_run_chat_semantic_layer_verified_match_overrides_text_match(monkeypatch):
    # Prose reply text-matches "customer-capacity-allocation", but the
    # semantic layer's governed query says move-forecast-summary - the
    # verified, structural answer should win.
    monkeypatch.setattr(
        "app.chat.stream_chat_completion",
        _fake_stream_by_prompt(
            sql_reply="SELECT id, name FROM data_products WHERE id = 'move-forecast-summary'",
            prose_reply="Specific Customer Capacity Allocation looks relevant.",
        ),
    )
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "move-forecast-summary", "name": "FAB Production Move Forecast Summary"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    events = await _collect_events(run_chat("need a report", "en", CATALOG))
    assert events[-1]["matched_products"] == ["move-forecast-summary"]


async def test_run_chat_semantic_layer_uses_llm_sql_model_when_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_sql_model", "llama3-groq-tool-use:8b")
    models_seen = []

    async def _fake(messages, model=None):
        prompt = messages[0]["content"]
        models_seen.append(model)
        if "Write ONE SQL" in prompt:
            yield "SELECT id, name FROM data_products WHERE id = 'move-forecast-summary'"
        else:
            yield "Some prose reply."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "move-forecast-summary", "name": "FAB Production Move Forecast Summary"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    await _collect_events(run_chat("need a report", "en", CATALOG))
    # First call (prose reply) uses the default model (None -> settings.llm_model);
    # second call (SQL generation) is explicitly routed to the configured SQL model.
    assert models_seen == [None, "llama3-groq-tool-use:8b"]


async def test_run_chat_semantic_layer_no_match_short_circuits_before_wrenai(monkeypatch):
    monkeypatch.setattr(
        "app.chat.stream_chat_completion",
        _fake_stream_by_prompt(sql_reply="NO_MATCH", prose_reply="Sorry, nothing matches."),
    )
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    called = False

    async def _should_not_be_called(sql):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _should_not_be_called)

    events = await _collect_events(run_chat("employee salary lookup", "en", CATALOG))
    assert events[-1]["matched_products"] == []
    assert called is False  # NO_MATCH never even reaches the governed engine


async def test_run_chat_semantic_layer_failure_falls_back_to_text_match(monkeypatch):
    monkeypatch.setattr(
        "app.chat.stream_chat_completion",
        _fake_stream_by_prompt(
            sql_reply="SELECT id FROM data_products WHERE id = 'customer-capacity-allocation'",
            prose_reply="Specific Customer Capacity Allocation is a great match.",
        ),
    )
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _boom(sql):
        raise RuntimeError("MDL not built")

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _boom)

    events = await _collect_events(run_chat("capacity please", "en", CATALOG))
    final = events[-1]
    assert final["matched_products"] == ["customer-capacity-allocation"]
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("Semantic layer verification failed" in t for t in step_texts)
