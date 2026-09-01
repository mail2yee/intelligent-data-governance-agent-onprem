"""
Personal chat preference memory - item 1 of the user's agent-improvement
wishlist ("remember the preference from personal chat history").

Two scope decisions were confirmed with the user via AskUserQuestion
before building this:

1. **Identity**: this app has no real SSO/OIDC yet (the same gap
   main.py's submit_approval() already has - see its docstring), so
   "the same user across sessions" is a lightweight, self-declared
   `user_key` (a name/email typed into the frontend's profile dialog,
   persisted in the browser's localStorage) rather than a real
   authenticated identity. Anyone can claim any user_key - this is a
   personalization nicety, not a security boundary, and the user can
   view/clear their own remembered list at any time (see main.py's
   /api/preferences endpoints).
2. **What "preference" means**: extracted, concrete preference
   statements (e.g. "usually asks about customer capacity data"), not
   raw stored transcripts - a short, capped (MAX_PREFERENCES), LLM-
   maintained list that gets spliced into future prompts as background
   context (see chat.py's _format_preferences()), the same "structural
   context, not a new judgment call" pattern already used for
   `history` (see chat.py's run_chat() docstring).

Updating the list is deliberately best-effort and non-blocking, same
fallback philosophy as chat.py's record_unmatched_query(): a failure
here must never break the actual chat reply the user is waiting on.
"""

import json
import logging

from .db import UserPreference, async_session
from .integrations.llm_client import stream_chat_completion

logger = logging.getLogger("dgo")

MAX_PREFERENCES = 8


async def get_preferences(user_key: str) -> list[str]:
    async with async_session() as session:
        row = await session.get(UserPreference, user_key)
        return list(row.preferences) if row else []


async def clear_preferences(user_key: str) -> None:
    async with async_session() as session:
        row = await session.get(UserPreference, user_key)
        if row:
            await session.delete(row)
            await session.commit()


async def _save_preferences(user_key: str, preferences: list[str]) -> None:
    async with async_session() as session:
        row = await session.get(UserPreference, user_key)
        if row:
            row.preferences = preferences
        else:
            session.add(UserPreference(user_key=user_key, preferences=preferences))
        await session.commit()


def _build_extraction_prompt(existing: list[str], user_msg: str, reply: str) -> str:
    existing_block = json.dumps(existing, ensure_ascii=False) if existing else "(none yet)"
    return f"""
    You maintain a short list of a user's remembered preferences based on
    their chat history with a data-catalog assistant. A preference is a
    short, concrete fact useful for interpreting a *future* ambiguous
    question from the same user (e.g. "usually asks about customer
    capacity data", "prefers replies in Traditional Chinese", "works on
    sales planning reports"). Never invent a preference the conversation
    below doesn't actually evidence.

    Existing remembered preferences for this user (already de-duplicated,
    max {MAX_PREFERENCES} items):
    {existing_block}

    Latest exchange:
    User: "{user_msg}"
    Assistant: "{reply}"

    Decide whether this exchange reveals a new or updated preference
    worth remembering. If so, reply with the FULL updated list as a JSON
    array of short strings (max {MAX_PREFERENCES} items - if adding a new
    one would exceed that, drop the least useful existing one). If
    nothing new or noteworthy, reply with exactly:
    NO_CHANGE
    Reply with the JSON array (or NO_CHANGE) only - no explanation, no
    markdown code fences.
    """


def _parse_extraction_reply(text: str) -> list[str] | None:
    """None means "no change" (either the LLM said so, or its reply
    couldn't be parsed as a valid list - treated the same way, since a
    malformed reply is not a trustworthy update)."""
    cleaned = text.strip()
    if not cleaned or cleaned.upper() == "NO_CHANGE":
        return None
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
    try:
        parsed = json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not all(isinstance(p, str) for p in parsed):
        return None
    return [p.strip() for p in parsed if p.strip()][:MAX_PREFERENCES]


async def observe_and_update(user_key: str, user_msg: str, reply: str) -> None:
    """Best-effort: fetch this user's existing preferences, ask the LLM
    whether the latest exchange reveals anything new, save if so. Never
    raises - logs and returns on any failure (LLM unreachable, malformed
    reply, DB error), same as record_unmatched_query()."""
    try:
        existing = await get_preferences(user_key)
        extraction_reply = ""
        # Deliberately NOT settings.llm_sql_model (unlike chat.py's SQL-
        # generation call) - confirmed via live testing 2026-09-01 that
        # the tool-calling/strict-SQL-tuned model this app configures
        # there (llama3-groq-tool-use:8b) reliably produces malformed
        # output for this open-ended "extract preferences as a JSON
        # array of strings" task (e.g. a nested `[{"preferance": "..."}]`
        # object instead of `["..."]`), while the default conversational
        # model handles it correctly - this task is closer to summarization
        # than to strict-syntax generation.
        async for piece in stream_chat_completion(
            [{"role": "user", "content": _build_extraction_prompt(existing, user_msg, reply)}]
        ):
            extraction_reply += piece
        updated = _parse_extraction_reply(extraction_reply)
        if updated is not None and updated != existing:
            await _save_preferences(user_key, updated)
            logger.info("Preferences updated for %s: %s", user_key, updated)
    except Exception as e:
        logger.warning("Failed to update preferences for %s: %s", user_key, e)
