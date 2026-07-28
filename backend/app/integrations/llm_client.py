"""
On-prem LLM integration.

UNCONFIRMED: this assumes the on-prem model is served behind an
OpenAI-compatible chat completions API (the common shape for vLLM / TGI /
Ollama-style gateways) - i.e. `POST {LLM_BASE_URL}/chat/completions` with
`{"model", "messages", "stream": true}`, returning SSE lines of
`data: {"choices":[{"delta":{"content": "..."}}]}` terminated by
`data: [DONE]`.

If the real on-prem gateway's request/response shape differs, this is the
only file that should need to change - callers just consume
`stream_chat_completion()` as an async generator of text chunks.
"""

import json
from collections.abc import AsyncIterator

import httpx

from ..config import settings


async def stream_chat_completion(messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
    """Yields text chunks as they arrive from the LLM. Raises on HTTP errors.

    `model` overrides `settings.llm_model` for this call - used by chat.py
    to send its SQL-generation prompt to a tool-calling-tuned model
    (`settings.llm_sql_model`) while the free-text reply keeps using the
    default conversational model. Both still go through the same
    OpenAI-compatible gateway/endpoint, only the `model` field differs.
    """
    url = f"{settings.llm_base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    payload = {"model": model or settings.llm_model, "messages": messages, "stream": True}

    async with (
        httpx.AsyncClient(timeout=60) as client,
        client.stream("POST", url, json=payload, headers=headers) as resp,
    ):
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]" or not data:
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content")
            if piece:
                yield piece
