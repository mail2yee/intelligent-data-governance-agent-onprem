from sqlalchemy import select

from app.db import UnmatchedQuery, async_session
from scripts.review_unmatched_queries import main


async def test_no_unreviewed_rows_is_a_noop(capsys):
    await main()
    assert "No unreviewed queries" in capsys.readouterr().out


async def test_marks_all_fetched_rows_as_reviewed(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "1 looks like a greeting - suggest adding 'sup' as a keyword. 2 looks like a real request."

    monkeypatch.setattr("scripts.review_unmatched_queries.stream_chat_completion", _fake_stream)

    async with async_session() as session:
        session.add(UnmatchedQuery(message="sup dude", lang="en"))
        session.add(UnmatchedQuery(message="employee salary lookup", lang="en"))
        await session.commit()

    await main()

    async with async_session() as session:
        rows = (await session.execute(select(UnmatchedQuery))).scalars().all()
    assert len(rows) == 2
    assert all(row.reviewed for row in rows)


async def test_already_reviewed_rows_are_not_resurfaced(monkeypatch):
    seen_messages: list[str] = []

    async def _fake_stream(messages, model=None):
        seen_messages.append(messages[0]["content"])
        yield "nothing to suggest"

    monkeypatch.setattr("scripts.review_unmatched_queries.stream_chat_completion", _fake_stream)

    async with async_session() as session:
        session.add(UnmatchedQuery(message="already handled", lang="en", reviewed=True))
        await session.commit()

    await main()

    assert seen_messages == []  # no unreviewed rows, so the LLM is never even called
