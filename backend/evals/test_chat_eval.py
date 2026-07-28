"""
DeepEval-based eval suite for /api/chat's semantic-layer matching.

NOT part of the fast `pytest` suite in tests/ (pyproject.toml's
`testpaths = ["tests"]` already excludes this directory from a bare
`pytest` run - this must be invoked explicitly: `pytest evals/`).
Deliberately separate because this hits the real, running Docker Compose
stack (real Postgres, real WrenAI, real Ollama) - slow, non-deterministic,
and requires local setup (`docker compose up`, a local Ollama with a judge
model pulled), unlike tests/'s fast, fully-mocked, SQLite-backed suite.

Honest framing, same as the sibling agent_mem0_poc repo's eval harness:
this is a repeatable *signal*, not a certified quality gate. LLM output is
non-deterministic, so each golden query runs N_TRIALS times and results
are aggregated into a pass rate rather than asserted trial-by-trial. The
PASS_RATE_FLOOR below is deliberately set low (see its comment) - it's
meant to catch a genuine regression (something breaking further), not to
claim the current ~50-65% keyword-precision reliability documented in
HANDOFF.md is good enough.

Setup:
    pip install -r requirements-eval.txt
    docker compose up -d --build          # real stack must be running
    ollama pull qwen2.5:latest             # or whatever DGO_EVAL_JUDGE_MODEL is

Run:
    DGO_API_BASE_URL=http://localhost:8000 pytest evals/ -v -s
"""

import json
import os

import httpx
import pytest
from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.models import OllamaModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from app.integrations.datahub_client import MOCK_CATALOG
from evals.golden_queries import GOLDEN_QUERIES

API_BASE_URL = os.environ.get("DGO_API_BASE_URL", "http://localhost:8000")
JUDGE_MODEL_NAME = os.environ.get("DGO_EVAL_JUDGE_MODEL", "qwen2.5:latest")
JUDGE_OLLAMA_BASE_URL = os.environ.get("DGO_EVAL_OLLAMA_BASE_URL", "http://localhost:11434")
N_TRIALS = int(os.environ.get("DGO_EVAL_TRIALS", "3"))

# Deliberately low - see module docstring. Today's known reliability
# (HANDOFF.md: ~50-65% correct after the search_text/script fix, small
# local judge model too) means a strict threshold would fail on every
# run without signaling anything new. Raise this once a stronger judge
# or a stronger production LLM is in place, or once the keyword-
# specificity issue in HANDOFF.md is addressed.
PASS_RATE_FLOOR = 0.3

_ALL_CATALOG_IDS = frozenset(MOCK_CATALOG.keys())
for _gq in GOLDEN_QUERIES:
    assert _gq.expected_product_ids <= _ALL_CATALOG_IDS, (
        f"golden query {_gq.id!r} expects an id not in MOCK_CATALOG - fix golden_queries.py"
    )


def _judge() -> OllamaModel:
    return OllamaModel(model=JUDGE_MODEL_NAME, base_url=JUDGE_OLLAMA_BASE_URL)


async def _run_chat(message: str, lang: str) -> dict:
    """Calls the real, running backend's /api/chat SSE endpoint and returns
    the `final` event's payload (reply, matched_products)."""
    async with (
        httpx.AsyncClient(timeout=60) as client,
        client.stream("POST", f"{API_BASE_URL}/api/chat", json={"message": message, "lang": lang}) as resp,
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


@pytest.mark.parametrize("golden", GOLDEN_QUERIES, ids=lambda g: g.id)
async def test_golden_query(golden):
    trials = [await _run_chat(golden.message, golden.lang) for _ in range(N_TRIALS)]

    # Hard, structural assertion - must hold on every single trial, no LLM
    # judge involved. This is a regression guard on WrenAI's governance
    # (see wrenai_client.py): matched_products must never contain an id
    # that isn't a real catalog entry.
    for trial in trials:
        matched = set(trial["matched_products"])
        assert matched <= _ALL_CATALOG_IDS, (
            f"{golden.id}: fabricated product id(s) {matched - _ALL_CATALOG_IDS} - "
            "WrenAI governance should make this impossible, this is a real regression"
        )

    judge = _judge()
    test_cases = []
    for trial in trials:
        matched = set(trial["matched_products"])
        if golden.in_catalog:
            # Ground the Faithfulness check in the real fields of whichever
            # products actually got matched (empty list if none matched -
            # that's a separate, already-covered miss, not this metric's job).
            context = [
                f"{field}: {MOCK_CATALOG[pid].get(field, '')}"
                for pid in matched
                for field in ("name", "description", "maturity_level", "data_quality_score")
            ] or ["(no product was matched)"]
            test_cases.append(
                LLMTestCase(
                    input=golden.message,
                    actual_output=trial["reply"],
                    retrieval_context=context,
                )
            )
        else:
            test_cases.append(
                LLMTestCase(
                    input=golden.message,
                    actual_output=trial["reply"],
                    # Full catalog, so the judge can confirm the reply
                    # correctly declines rather than inventing a match.
                    retrieval_context=[MOCK_CATALOG[pid]["name"] for pid in _ALL_CATALOG_IDS],
                )
            )

    precision_metric = GEval(
        name="RecommendationPrecision",
        model=judge,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        criteria=(
            "Given the user's request (input) and the assistant's reply (actual_output), "
            "judge whether the reply only recommends data subjects that are genuinely "
            "relevant to the request. Penalize replies that recommend an unrelated or "
            "only tangentially-related data subject in addition to a correct one."
        ),
    )
    metrics = [precision_metric]
    if golden.in_catalog:
        metrics += [
            FaithfulnessMetric(model=judge),
            AnswerRelevancyMetric(model=judge),
        ]

    result = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        display_config=DisplayConfig(print_results=False, show_indicator=False),
        async_config=AsyncConfig(run_async=False),
    )
    all_metric_results = [m for tc_result in result.test_results for m in tc_result.metrics_data]
    pass_rate = sum(1 for m in all_metric_results if m.success) / len(all_metric_results)
    print(f"\n[{golden.id}] pass_rate={pass_rate:.2f} over {len(all_metric_results)} metric evaluations")

    assert pass_rate >= PASS_RATE_FLOOR, (
        f"{golden.id}: pass rate {pass_rate:.2f} below floor {PASS_RATE_FLOOR} - "
        "a real regression, not just today's known keyword-precision gap"
    )
