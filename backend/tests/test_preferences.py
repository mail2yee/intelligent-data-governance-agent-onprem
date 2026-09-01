import json

from app import preferences

USER = "tim@example.com"


async def test_get_preferences_empty_for_unknown_user():
    assert await preferences.get_preferences(USER) == []


async def test_save_and_get_preferences_roundtrip():
    await preferences._save_preferences(USER, ["usually asks about capacity data"])
    assert await preferences.get_preferences(USER) == ["usually asks about capacity data"]

    await preferences._save_preferences(USER, ["updated preference"])
    assert await preferences.get_preferences(USER) == ["updated preference"]


async def test_clear_preferences():
    await preferences._save_preferences(USER, ["something"])
    await preferences.clear_preferences(USER)
    assert await preferences.get_preferences(USER) == []


async def test_clear_preferences_on_unknown_user_is_a_noop():
    await preferences.clear_preferences("nobody@example.com")  # must not raise


def test_parse_extraction_reply_no_change():
    assert preferences._parse_extraction_reply("NO_CHANGE") is None
    assert preferences._parse_extraction_reply("  no_change  ") is None
    assert preferences._parse_extraction_reply("") is None


def test_parse_extraction_reply_valid_json_list():
    assert preferences._parse_extraction_reply('["prefers Traditional Chinese"]') == [
        "prefers Traditional Chinese"
    ]


def test_parse_extraction_reply_strips_markdown_fences():
    raw = '```json\n["usually asks about capacity data"]\n```'
    assert preferences._parse_extraction_reply(raw) == ["usually asks about capacity data"]


def test_parse_extraction_reply_malformed_json_is_no_change():
    assert preferences._parse_extraction_reply("not valid json") is None


def test_parse_extraction_reply_non_list_json_is_no_change():
    assert preferences._parse_extraction_reply('{"a": "b"}') is None


def test_parse_extraction_reply_list_of_non_strings_is_no_change():
    assert preferences._parse_extraction_reply("[1, 2, 3]") is None


def test_parse_extraction_reply_caps_to_max_preferences():
    items = [f"pref {i}" for i in range(preferences.MAX_PREFERENCES + 3)]
    parsed = preferences._parse_extraction_reply(json.dumps(items))
    assert parsed is not None
    assert len(parsed) == preferences.MAX_PREFERENCES


def test_build_extraction_prompt_includes_existing_and_latest_exchange():
    prompt = preferences._build_extraction_prompt(
        ["prefers Traditional Chinese"], "capacity please", "here you go"
    )
    assert "prefers Traditional Chinese" in prompt
    assert "capacity please" in prompt
    assert "here you go" in prompt
    assert "NO_CHANGE" in prompt


def test_build_extraction_prompt_handles_no_existing_preferences():
    prompt = preferences._build_extraction_prompt([], "hi", "hello")
    assert "(none yet)" in prompt


async def test_observe_and_update_saves_new_preferences(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield '["usually asks about customer capacity data"]'

    monkeypatch.setattr("app.preferences.stream_chat_completion", _fake_stream)

    await preferences.observe_and_update(USER, "capacity please", "here's the capacity data")
    assert await preferences.get_preferences(USER) == ["usually asks about customer capacity data"]


async def test_observe_and_update_no_change_does_not_save(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "NO_CHANGE"

    monkeypatch.setattr("app.preferences.stream_chat_completion", _fake_stream)

    await preferences.observe_and_update(USER, "hi", "hello")
    assert await preferences.get_preferences(USER) == []


async def test_observe_and_update_swallows_llm_failure(monkeypatch):
    async def _broken_stream(messages, model=None):
        raise ConnectionError("no route to host")
        yield  # pragma: no cover

    monkeypatch.setattr("app.preferences.stream_chat_completion", _broken_stream)

    await preferences.observe_and_update(USER, "hi", "hello")  # must not raise
    assert await preferences.get_preferences(USER) == []


async def test_observe_and_update_swallows_malformed_reply(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "this is not json"

    monkeypatch.setattr("app.preferences.stream_chat_completion", _fake_stream)

    await preferences.observe_and_update(USER, "hi", "hello")  # must not raise
    assert await preferences.get_preferences(USER) == []
