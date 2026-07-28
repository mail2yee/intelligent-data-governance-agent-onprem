"""
stream_chat_completion()'s actual SSE-parsing logic was previously never
exercised by any test - every caller-side test (test_chat.py) mocks the
whole function out, so a regression in the real httpx/SSE handling
wouldn't have been caught until manual testing. These use httpx's built-in
MockTransport (no new dependency) to simulate a real streaming response.
"""

import json

import httpx
import pytest

from app.config import settings
from app.integrations.llm_client import stream_chat_completion

# Must capture the real class before any test monkeypatches
# app.integrations.llm_client.httpx.AsyncClient - that patches the same
# `httpx` module object llm_client.py imported (it does `import httpx`,
# not `from httpx import AsyncClient`), so the factory below would call
# itself recursively if it referenced httpx.AsyncClient by name instead.
_RealAsyncClient = httpx.AsyncClient


def _client_factory(sse_body: bytes, captured_requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    return factory


async def _collect(agen):
    return [piece async for piece in agen]


async def test_stream_chat_completion_yields_content_pieces_in_order(monkeypatch):
    body = (
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    monkeypatch.setattr("app.integrations.llm_client.httpx.AsyncClient", _client_factory(body, []))

    pieces = await _collect(stream_chat_completion([{"role": "user", "content": "hi"}]))
    assert pieces == ["Hel", "lo"]


async def test_stream_chat_completion_skips_malformed_and_empty_lines(monkeypatch):
    body = (
        b"data: not valid json\n\n"
        b"data: \n\n"
        b'data: {"choices":[]}\n\n'
        b'data: {"choices":[{"delta":{}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    monkeypatch.setattr("app.integrations.llm_client.httpx.AsyncClient", _client_factory(body, []))

    pieces = await _collect(stream_chat_completion([{"role": "user", "content": "hi"}]))
    assert pieces == ["ok"]


async def test_stream_chat_completion_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr("app.integrations.llm_client.httpx.AsyncClient", factory)

    with pytest.raises(httpx.HTTPStatusError):
        await _collect(stream_chat_completion([{"role": "user", "content": "hi"}]))


async def test_stream_chat_completion_sends_model_override_and_api_key(monkeypatch):
    captured: list[httpx.Request] = []
    body = b"data: [DONE]\n\n"
    monkeypatch.setattr("app.integrations.llm_client.httpx.AsyncClient", _client_factory(body, captured))
    monkeypatch.setattr(settings, "llm_api_key", "secret-key")
    monkeypatch.setattr(settings, "llm_model", "default-model")

    await _collect(stream_chat_completion([{"role": "user", "content": "hi"}], model="override-model"))

    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert payload["model"] == "override-model"
    assert captured[0].headers["Authorization"] == "Bearer secret-key"


async def test_stream_chat_completion_uses_default_model_when_no_override(monkeypatch):
    captured: list[httpx.Request] = []
    body = b"data: [DONE]\n\n"
    monkeypatch.setattr("app.integrations.llm_client.httpx.AsyncClient", _client_factory(body, captured))
    monkeypatch.setattr(settings, "llm_model", "default-model")
    monkeypatch.setattr(settings, "llm_api_key", "")

    await _collect(stream_chat_completion([{"role": "user", "content": "hi"}]))

    payload = json.loads(captured[0].content)
    assert payload["model"] == "default-model"
    assert "Authorization" not in captured[0].headers
