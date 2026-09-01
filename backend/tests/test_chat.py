import json

import pytest
from sqlalchemy import select

from app.chat import (
    GREETING_REPLY,
    _extract_sql,
    _format_history,
    _format_preferences,
    build_prompt,
    build_sql_prompt,
    is_greeting,
    keyword_search,
    local_rule_match,
    not_found_reply,
    record_unmatched_query,
    run_chat,
    sse_event,
)
from app.db import UnmatchedQuery, async_session

KEYWORD_CATALOG = {
    "customer-capacity-allocation": {
        "name": "Specific Customer Capacity Allocation",
        "description": "為特定VIP客戶配置的晶圓代工產能。",
        "owner": "capacity_director@example.com",
        "maturity_level": "Gold",
        "data_quality_score": "99%",
        "frequency": "DAILY",
        "tables_joined": "capacity_plan, customer_commitment",
        "db_type": "PostgreSQL",
        "db_host": "h",
        "db_port": "5432",
        "db_schema": "capacity_mgmt",
    },
    "move-forecast-summary": {
        "name": "FAB Production Move Forecast Summary",
        "description": "晶圓廠生產Move與 WIP 預估。",
        "owner": "fab_ops_owner@example.com",
        "maturity_level": "Gold",
        "data_quality_score": "98%",
        "frequency": "HOURLY",
        "tables_joined": "wip_moves, tool_bottleneck",
        "db_type": "PostgreSQL",
        "db_host": "h",
        "db_port": "5432",
        "db_schema": "production_forecast",
    },
}

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


@pytest.mark.parametrize(
    "msg",
    [
        "hi",
        "Hello",
        "hey!",
        "你好",
        "早安",
        "hi there",
        "  hello  ",
        "hi how are you?",
        "hey what's up",
        "hello, how are you doing today?",
        "hi how r u?",
        "你好嗎",
        "您好嗎",
    ],
)
def test_is_greeting_true(msg):
    assert is_greeting(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "我想分析特定客戶投片產能與實際出貨預估",
        "what is gold maturity",
        "",
        "hi, I want to look at customer capacity data",
        "hi customer capacity allocation report",
    ],
)
def test_is_greeting_false(msg):
    assert is_greeting(msg) is False


def test_sse_event_format():
    event = sse_event("step", text="hello")
    assert event.startswith("data: ")
    assert event.endswith("\n\n")
    payload = json.loads(event[len("data: ") :].strip())
    assert payload == {"type": "step", "text": "hello"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SELECT id FROM data_products", "SELECT id FROM data_products"),
        ("SELECT id FROM data_products;", "SELECT id FROM data_products"),
        ("```sql\nSELECT id FROM data_products\n```", "SELECT id FROM data_products"),
        ("```\nSELECT id FROM data_products\n```", "SELECT id FROM data_products"),
        ("NO_MATCH", "NO_MATCH"),
    ],
)
def test_extract_sql(raw, expected):
    assert _extract_sql(raw) == expected


def test_local_rule_match_capacity_zh():
    matched, reply = local_rule_match("我想分析特定客戶產能分配", "zh", CATALOG)
    assert matched == ["customer-capacity-allocation"]
    assert "Specific Customer Capacity Allocation" in reply


def test_local_rule_match_no_match():
    matched, reply = local_rule_match("what is the weather", "en", CATALOG)
    assert matched == []
    assert reply == not_found_reply(CATALOG, "en")


async def test_keyword_search_all_keywords_must_match():
    matched, reply = await keyword_search("capacity 客戶", "zh", KEYWORD_CATALOG)
    assert matched == ["customer-capacity-allocation"]
    assert "1" in reply


async def test_keyword_search_single_keyword_matching_both_returns_both():
    # "晶圓" (wafer) appears in both catalog entries' descriptions.
    matched, reply = await keyword_search("晶圓", "zh", KEYWORD_CATALOG)
    assert set(matched) == {"customer-capacity-allocation", "move-forecast-summary"}
    assert "2" in reply


async def test_keyword_search_no_match_returns_not_found_reply():
    matched, reply = await keyword_search("nonexistent keyword", "en", KEYWORD_CATALOG)
    assert matched == []
    assert reply == not_found_reply(KEYWORD_CATALOG, "en")


async def test_keyword_search_blank_query_returns_not_found_without_querying_db():
    matched, reply = await keyword_search("   ", "en", KEYWORD_CATALOG)
    assert matched == []
    assert reply == not_found_reply(KEYWORD_CATALOG, "en")


async def test_run_chat_keyword_mode_yields_only_final_event_no_llm_call(monkeypatch):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("LLM should not be called in keyword mode")
        yield  # pragma: no cover

    monkeypatch.setattr("app.chat.stream_chat_completion", _should_not_be_called)

    events = await _collect_events(run_chat("capacity 客戶", "zh", KEYWORD_CATALOG, mode="keyword"))
    assert [e["type"] for e in events] == ["final"]
    assert events[0]["matched_products"] == ["customer-capacity-allocation"]


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


async def test_run_chat_llm_failure_and_no_local_match_still_reports_zero_hallucination(monkeypatch):
    # Both fallback layers come up empty: the first LLM call fails outright
    # (falls back to local_rule_match), and local_rule_match itself finds
    # no keyword match either - matched_products must end up [] with the
    # zero-hallucination step emitted, not silently skipped.
    async def _broken_stream(messages):
        raise ConnectionError("no route to host")
        yield  # pragma: no cover

    monkeypatch.setattr("app.chat.stream_chat_completion", _broken_stream)

    events = await _collect_events(run_chat("random unrelated question", "en", CATALOG))
    final = events[-1]
    assert final["matched_products"] == []
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("Zero Hallucination" in t for t in step_texts)


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


async def test_run_chat_no_match_records_unmatched_query(monkeypatch):
    monkeypatch.setattr(
        "app.chat.stream_chat_completion",
        _fake_stream_by_prompt(sql_reply="NO_MATCH", prose_reply="Sorry, nothing matches."),
    )
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    await _collect_events(run_chat("what is the weather", "en", CATALOG))

    async with async_session() as session:
        rows = (await session.execute(select(UnmatchedQuery))).scalars().all()
    assert len(rows) == 1
    assert rows[0].message == "what is the weather"
    assert rows[0].lang == "en"
    assert rows[0].reviewed is False


async def test_record_unmatched_query_fails_gracefully(monkeypatch):
    def _broken_session():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.chat.async_session", _broken_session)
    await record_unmatched_query("test", "en")  # must not raise


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


async def test_run_chat_semantic_layer_failure_and_text_says_no_match(monkeypatch):
    # Semantic layer verification also fails here, but this time the
    # text-matching fallback it falls back to independently agrees
    # there's no match - matched_products must end up [], not whatever
    # the (never-verified) SQL reply implied.
    monkeypatch.setattr(
        "app.chat.stream_chat_completion",
        _fake_stream_by_prompt(
            sql_reply="SELECT id FROM data_products WHERE id = 'customer-capacity-allocation'",
            prose_reply="Sorry, no data subject in our catalog matches your request.",
        ),
    )
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _boom(sql):
        raise RuntimeError("MDL not built")

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _boom)

    events = await _collect_events(run_chat("capacity please", "en", CATALOG))
    final = events[-1]
    assert final["matched_products"] == []
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("Zero Hallucination" in t for t in step_texts)


def test_format_history_empty_returns_empty_string():
    assert _format_history(None) == ""
    assert _format_history([]) == ""


def test_format_history_renders_prior_turns_in_order():
    history = [
        {"role": "user", "content": "我想要做一個 report"},
        {"role": "assistant", "content": "可以說明是哪個方向嗎？"},
    ]
    rendered = _format_history(history)
    assert "[Conversation so far]" in rendered
    assert "user: 我想要做一個 report" in rendered
    assert "assistant: 可以說明是哪個方向嗎？" in rendered
    # order preserved
    assert rendered.index("user: 我想要做一個 report") < rendered.index("assistant: 可以說明是哪個方向嗎？")


def test_build_prompt_omits_conversation_block_with_no_history():
    prompt = build_prompt("capacity please", "en", CATALOG)
    assert "[Conversation so far]" not in prompt
    assert "follow-up" not in prompt.lower()


def test_build_prompt_includes_history_and_followup_hint():
    history = [{"role": "assistant", "content": "Which area is your report about?"}]
    prompt = build_prompt("capacity", "en", CATALOG, history)
    assert "[Conversation so far]" in prompt
    assert "Which area is your report about?" in prompt
    assert "follow-up" in prompt.lower()


def test_build_sql_prompt_includes_history_and_followup_hint():
    history = [{"role": "user", "content": "我想要做一個 report"}]
    prompt = build_sql_prompt("產能面的", KEYWORD_CATALOG, history)
    assert "[Conversation so far]" in prompt
    assert "我想要做一個 report" in prompt
    assert "follow-up" in prompt.lower()


async def test_run_chat_passes_history_to_both_llm_calls(monkeypatch):
    # A short follow-up ("產能面的") on its own wouldn't extract a useful
    # keyword without knowing what was already asked - confirms history
    # actually reaches both the prose-reply prompt and the SQL-generation
    # prompt, not just one of them.
    seen_prompts = []

    async def _fake(messages, model=None):
        prompt = messages[0]["content"]
        seen_prompts.append(prompt)
        if "Write ONE SQL" in prompt:
            yield "SELECT id, name FROM data_products WHERE id = 'customer-capacity-allocation'"
        else:
            yield "Specific Customer Capacity Allocation looks relevant."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "customer-capacity-allocation", "name": "Specific Customer Capacity Allocation"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    history = [
        {"role": "user", "content": "我想要做一個 report 需要哪些 data source?"},
        {"role": "assistant", "content": "可以說明一下想分析的報表主要跟哪個方向有關嗎？"},
    ]
    events = await _collect_events(run_chat("產能面的", "zh", CATALOG, history=history))
    assert events[-1]["matched_products"] == ["customer-capacity-allocation"]
    assert len(seen_prompts) == 2
    assert all("[Conversation so far]" in p for p in seen_prompts)
    assert all("我想要做一個 report" in p for p in seen_prompts)


async def test_run_chat_keyword_mode_ignores_history(monkeypatch):
    # Keyword mode has no LLM to give context to - history must be
    # accepted without error but have zero effect on the deterministic
    # ILIKE match.
    events = await _collect_events(
        run_chat(
            "capacity 客戶",
            "zh",
            KEYWORD_CATALOG,
            mode="keyword",
            history=[{"role": "user", "content": "irrelevant prior turn"}],
        )
    )
    assert events[-1]["matched_products"] == ["customer-capacity-allocation"]


def test_format_preferences_empty_returns_empty_string():
    assert _format_preferences(None) == ""
    assert _format_preferences([]) == ""


def test_format_preferences_renders_list():
    rendered = _format_preferences(["usually asks about capacity data", "prefers zh replies"])
    assert "Remembered preferences" in rendered
    assert "- usually asks about capacity data" in rendered
    assert "- prefers zh replies" in rendered


def test_build_prompt_omits_preferences_block_with_none_given():
    prompt = build_prompt("capacity please", "en", CATALOG)
    assert "Remembered preferences" not in prompt


def test_build_prompt_includes_preferences_block():
    prompt = build_prompt("capacity please", "en", CATALOG, preferences=["usually asks about capacity data"])
    assert "Remembered preferences" in prompt
    assert "usually asks about capacity data" in prompt


def test_build_sql_prompt_includes_preferences_block():
    prompt = build_sql_prompt(
        "產能面的", KEYWORD_CATALOG, preferences=["usually asks about customer capacity data"]
    )
    assert "Remembered preferences" in prompt
    assert "usually asks about customer capacity data" in prompt


async def test_run_chat_passes_preferences_to_both_llm_calls(monkeypatch):
    seen_prompts = []

    async def _fake(messages, model=None):
        prompt = messages[0]["content"]
        seen_prompts.append(prompt)
        if "Write ONE SQL" in prompt:
            yield "SELECT id, name FROM data_products WHERE id = 'customer-capacity-allocation'"
        else:
            yield "Specific Customer Capacity Allocation looks relevant."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "customer-capacity-allocation", "name": "Specific Customer Capacity Allocation"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    events = await _collect_events(
        run_chat("something", "en", CATALOG, preferences=["usually asks about customer capacity data"])
    )
    assert events[-1]["matched_products"] == ["customer-capacity-allocation"]
    assert len(seen_prompts) == 2
    assert all("usually asks about customer capacity data" in p for p in seen_prompts)


async def test_run_chat_updates_preferences_when_user_key_given(monkeypatch):
    async def _fake(messages, model=None):
        yield "Specific Customer Capacity Allocation looks relevant."

    async def _broken_resolve(sql):
        raise Exception("WrenAI unavailable in this test")

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)
    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _broken_resolve)

    captured = {}

    async def _fake_observe(user_key, user_msg, reply):
        captured["user_key"] = user_key
        captured["user_msg"] = user_msg
        captured["reply"] = reply

    monkeypatch.setattr("app.chat.preferences_mod.observe_and_update", _fake_observe)

    await _collect_events(run_chat("capacity please", "en", CATALOG, user_key="tim@example.com"))
    assert captured["user_key"] == "tim@example.com"
    assert captured["user_msg"] == "capacity please"


async def test_run_chat_skips_preferences_update_without_user_key(monkeypatch):
    async def _fake(messages, model=None):
        yield "Specific Customer Capacity Allocation looks relevant."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("observe_and_update should not be called without a user_key")

    monkeypatch.setattr("app.chat.preferences_mod.observe_and_update", _should_not_be_called)

    await _collect_events(run_chat("capacity please", "en", CATALOG))  # must not raise


async def test_run_chat_skips_preferences_update_when_llm_unreachable(monkeypatch):
    async def _broken_stream(messages, model=None):
        raise ConnectionError("no route to host")
        yield  # pragma: no cover

    monkeypatch.setattr("app.chat.stream_chat_completion", _broken_stream)

    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("observe_and_update should not be called when the LLM is unreachable")

    monkeypatch.setattr("app.chat.preferences_mod.observe_and_update", _should_not_be_called)

    await _collect_events(run_chat("capacity please", "en", CATALOG, user_key="tim@example.com"))


async def test_run_chat_keyword_mode_skips_preferences_update(monkeypatch):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("observe_and_update should not be called in keyword mode")

    monkeypatch.setattr("app.chat.preferences_mod.observe_and_update", _should_not_be_called)

    await _collect_events(
        run_chat("capacity 客戶", "zh", KEYWORD_CATALOG, mode="keyword", user_key="tim@example.com")
    )


async def test_run_chat_km_match_answers_from_km_without_catalog_flow(monkeypatch):
    call_count = 0

    async def _fake(messages, model=None):
        nonlocal call_count
        call_count += 1
        prompt = messages[0]["content"]
        assert "policy assistant" in prompt  # only ever called with the KM prompt
        yield "Gold requires a 95%+ quality score, per the maturity policy."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)

    events = await _collect_events(run_chat("什麼是 Gold 等級？", "zh", CATALOG))
    assert call_count == 1  # catalog flow's build_prompt/build_sql_prompt calls never happened
    final = events[-1]
    assert final["type"] == "final"
    assert final["matched_products"] == []
    assert "95%" in final["reply"]
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("知識庫" in t for t in step_texts)


async def test_run_chat_km_no_keyword_hit_falls_through_to_catalog_flow(monkeypatch):
    async def _fake(messages, model=None):
        yield "Specific Customer Capacity Allocation looks relevant."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "customer-capacity-allocation", "name": "Specific Customer Capacity Allocation"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    events = await _collect_events(run_chat("capacity please", "en", CATALOG))
    assert events[-1]["matched_products"] == ["customer-capacity-allocation"]
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert not any("knowledge base" in t.lower() for t in step_texts)


async def test_run_chat_km_failure_falls_through_to_catalog_matching(monkeypatch):
    async def _fake(messages, model=None):
        prompt = messages[0]["content"]
        if "policy assistant" in prompt:
            raise ConnectionError("KM LLM call failed")
        yield "Specific Customer Capacity Allocation looks relevant."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)
    monkeypatch.setattr("app.chat.wrenai_client.sync_catalog", _noop_sync)

    async def _fake_resolve(sql):
        return [{"id": "customer-capacity-allocation", "name": "Specific Customer Capacity Allocation"}]

    monkeypatch.setattr("app.chat.wrenai_client.resolve_matches", _fake_resolve)

    # "gold" is a KM keyword, so this still routes into the KM path first,
    # but that path fails - must gracefully fall through to the normal
    # catalog-matching flow rather than erroring the whole turn out.
    events = await _collect_events(run_chat("gold capacity please", "en", CATALOG))
    final = events[-1]
    assert final["type"] == "final"
    assert final["matched_products"] == ["customer-capacity-allocation"]
    step_texts = [e["text"] for e in events if e["type"] == "step"]
    assert any("KM answer failed" in t for t in step_texts)


async def test_run_chat_km_prompt_includes_history(monkeypatch):
    seen_prompts = []

    async def _fake(messages, model=None):
        seen_prompts.append(messages[0]["content"])
        yield "Silver requires 80-95% quality, per the maturity policy."

    monkeypatch.setattr("app.chat.stream_chat_completion", _fake)

    history = [{"role": "assistant", "content": "Gold requires a 95%+ quality score."}]
    await _collect_events(run_chat("那 Silver 呢？maturity", "zh", CATALOG, history=history))
    assert len(seen_prompts) == 1
    assert "[Conversation so far]" in seen_prompts[0]
    assert "Gold requires a 95%+ quality score" in seen_prompts[0]
