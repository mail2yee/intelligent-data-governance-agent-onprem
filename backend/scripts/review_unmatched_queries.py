"""
Periodic offline review of unmatched chat queries (app/db.py's
UnmatchedQuery table - populated by chat.py's record_unmatched_query()
whenever run_chat()'s zero-hallucination check finds no catalog match).

**Why this exists, and why it's offline rather than live**: a live,
per-request LLM classification of "is this actually a greeting/chit-chat
that is_greeting()'s keyword check missed" was tried and reverted
2026-07-31 - a small local model proved unreliable at that 3-way
decision (kept misclassifying genuinely off-topic messages like "what's
the weather" as a greeting). This script sidesteps that reliability
problem entirely: the LLM here is only a *triage assistant* surfacing
candidate patterns for a human to read, not an unsupervised decision-
maker - a human still has to actually edit chat.py's GREETING_WORDS/
CHITCHAT_WORDS/CHITCHAT_PHRASES_ZH before any suggestion takes effect,
so the same unreliable model judgment that broke the live 3-way
classification is harmless here (worst case: a bad suggestion gets
ignored by whoever reads the output).

Usage:
    cd backend && python3 scripts/review_unmatched_queries.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import UnmatchedQuery, async_session  # noqa: E402
from app.integrations.llm_client import stream_chat_completion  # noqa: E402

REVIEW_PROMPT_TEMPLATE = """
The following user messages were sent to a data-catalog search assistant
and none of them matched anything in the catalog. Some of these are
likely just greetings or small talk that should have been caught before
even reaching the search step, rather than genuine (if uncataloged)
report requests.

Messages:
{messages}

List which of these (by number) look like pure greetings/small talk, and
suggest short keywords or phrases (in the same language/script as the
message) that could be added to a keyword-matching greeting filter to
catch similar messages automatically in the future. Do not suggest
anything for messages that look like a genuine, if uncataloged,
report/data request.
"""


async def main() -> None:
    async with async_session() as session:
        result = await session.execute(
            select(UnmatchedQuery)
            .where(UnmatchedQuery.reviewed.is_(False))
            .order_by(UnmatchedQuery.created_at)
        )
        rows = result.scalars().all()

    if not rows:
        print("No unreviewed queries.")
        return

    numbered = "\n".join(f"{i + 1}. [{row.lang}] {row.message}" for i, row in enumerate(rows))
    prompt = REVIEW_PROMPT_TEMPLATE.format(messages=numbered)

    print(f"Reviewing {len(rows)} unmatched quer{'y' if len(rows) == 1 else 'ies'} with the local LLM...\n")

    reply = ""
    async for piece in stream_chat_completion([{"role": "user", "content": prompt}]):
        reply += piece
    print(reply)

    async with async_session() as session:
        for row in rows:
            db_row = await session.get(UnmatchedQuery, row.id)
            if db_row:
                db_row.reviewed = True
        await session.commit()

    print(f"\nMarked {len(rows)} quer{'y' if len(rows) == 1 else 'ies'} as reviewed.")


if __name__ == "__main__":
    asyncio.run(main())
