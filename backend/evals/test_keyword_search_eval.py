"""
Hit-rate eval for the "general search" keyword mode (see
app/chat.py's keyword_search()) - the non-AI default search path: plain
ILIKE substring matching against data_products.search_text, where every
whitespace-separated keyword in the query must match (AND logic).

Unlike test_chat_eval.py's AI-mode suite, this needs no LLM judge at
all - keyword mode is fully deterministic, so "did it return the
expected product id(s)?" is a plain boolean check. Still lives in
evals/, not tests/, because it hits the real, running /api/chat
endpoint (real MariaDB-backed data_products table) rather than tests/'s
fully-mocked SQLite suite - this measures *real-world query accuracy*,
not code correctness (tests/test_chat.py's keyword_search() tests
already cover the ILIKE logic itself with clean, contrived strings).

The golden set (keyword_golden_queries.py) deliberately mixes clean,
well-formed keyword-style queries with realistic natural-language
phrasing (no manually-inserted keyword separation) - not an oversight.
A full Chinese sentence has no whitespace between words, so it becomes
ONE giant token that almost never appears verbatim in a catalog entry's
short description; a full English sentence requires every single word
(including "I", "want", "to") to independently match. Both are
realistic ways a user might type, per the UI's own search placeholder
text (which shows a full natural sentence as its example) - measuring
hit rate against only clean keyword-style queries would overstate
real-world accuracy. See keyword_golden_queries.py's `expect_match`
flag for which queries are known-working vs. known-limitation cases.

Run: pytest evals/test_keyword_search_eval.py -v -s
(needs the real stack up - same setup as test_chat_eval.py's "Evals"
section in backend/README.md, minus any LLM judge config - this file
doesn't use one at all.)
"""

import json
import os

import httpx

from app.integrations.datahub_client import MOCK_CATALOG
from evals.keyword_golden_queries import KEYWORD_GOLDEN_QUERIES

API_BASE_URL = os.environ.get("DGO_API_BASE_URL", "http://localhost:8000")

# Deliberately NOT 1.0 - and not meant to be raised to 1.0 by "fixing"
# the natural-phrasing queries below. Those aren't bugs, they're plain
# substring AND-matching's actual, inherent limitation (see module
# docstring). This floor exists to catch a real regression (something
# that used to match no longer matching), not to gate on 100% accuracy
# for a fundamentally imprecise matching strategy.
OVERALL_HIT_RATE_FLOOR = 0.5

_ALL_CATALOG_IDS = frozenset(MOCK_CATALOG.keys())
for _gq in KEYWORD_GOLDEN_QUERIES:
    assert _gq.expected_product_ids <= _ALL_CATALOG_IDS, (
        f"keyword golden query {_gq.id!r} expects an id not in MOCK_CATALOG - fix keyword_golden_queries.py"
    )


async def _run_keyword_search(message: str, lang: str) -> dict:
    """Calls the real, running backend's /api/chat SSE endpoint in
    keyword mode and returns the `final` event's payload."""
    async with (
        httpx.AsyncClient(timeout=30) as client,
        client.stream(
            "POST", f"{API_BASE_URL}/api/chat", json={"message": message, "lang": lang, "mode": "keyword"}
        ) as resp,
    ):
        resp.raise_for_status()
        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
    for line in buffer.split("\n\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        event = json.loads(line[len("data:") :].strip())
        if event.get("type") == "final":
            return event
    raise AssertionError(f"no final event in response for {message!r}")


async def test_keyword_search_never_regresses_on_known_working_queries():
    """Hard, per-query assertion (no floor/tolerance) for the
    `expect_match=True` subset - keyword mode is fully deterministic,
    so there's no non-determinism to tolerate here the way the AI-mode
    suite has to. A miss on one of these is a real regression, not
    sampling noise."""
    for golden in KEYWORD_GOLDEN_QUERIES:
        if not golden.expect_match:
            continue
        result = await _run_keyword_search(golden.message, golden.lang)
        matched = frozenset(result["matched_products"])
        assert matched == golden.expected_product_ids, (
            f"{golden.id}: expected {sorted(golden.expected_product_ids)}, got {sorted(matched)} - "
            "this is a known-working keyword pattern, a miss here is a real regression"
        )


async def test_keyword_search_overall_hit_rate():
    """One aggregate metric across the WHOLE golden set (including the
    natural-phrasing cases) - the realistic, blended number reflecting
    what a random real user actually experiences, not just the cases
    keyword matching is known to handle well. See module docstring for
    why some entries are *expected* to miss."""
    hits = 0
    misses = []
    for golden in KEYWORD_GOLDEN_QUERIES:
        result = await _run_keyword_search(golden.message, golden.lang)
        matched = frozenset(result["matched_products"])
        assert matched <= _ALL_CATALOG_IDS, (
            f"{golden.id}: fabricated product id(s) {matched - _ALL_CATALOG_IDS} - "
            "keyword_search() should only ever return real catalog ids"
        )
        if matched == golden.expected_product_ids:
            hits += 1
        else:
            misses.append(
                (golden.id, golden.expect_match, sorted(golden.expected_product_ids), sorted(matched))
            )

    hit_rate = hits / len(KEYWORD_GOLDEN_QUERIES)
    print(f"\nKeyword search overall hit rate: {hit_rate:.2f} ({hits}/{len(KEYWORD_GOLDEN_QUERIES)})")
    for golden_id, expected_to_work, expected, actual in misses:
        tag = "UNEXPECTED MISS" if expected_to_work else "known-limitation miss"
        print(f"  {tag} [{golden_id}]: expected {expected}, got {actual}")

    assert hit_rate >= OVERALL_HIT_RATE_FLOOR, (
        f"keyword search overall hit rate {hit_rate:.2f} below floor {OVERALL_HIT_RATE_FLOOR} - "
        "a real regression, not just the known natural-phrasing limitation"
    )
