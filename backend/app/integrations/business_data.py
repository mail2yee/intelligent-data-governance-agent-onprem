"""
Real NL-to-SQL against actual business data - not just catalog metadata
matching (see wrenai_client.py's module docstring for that distinction).

Added 2026-08-31 as item 2 of the user's agent-improvement wishlist.
Two governance decisions were confirmed with the user before building
this (via AskUserQuestion): (1) a product's real data can only ever be
queried after a ticket covering it has been APPROVED - main.py's new
`/api/catalog/{product_id}/query` endpoint enforces this server-side,
not just via frontend UI hiding (see that endpoint's own comment for why
this matters - the pre-existing `/connection` endpoint does NOT enforce
it, a known gap this new endpoint deliberately doesn't repeat); (2) since
the catalog's own db_host values are fictional (see datahub_client.py),
querying "real" data means a genuinely separate fake business database
(business_data/seed_capacity_mgmt.sql, a second Postgres container -
docker-compose.yml's fab-business-db) with its own WrenAI project
(wren/business_capacity_plan/) - deliberately a different engine/host/
credentials than the catalog's own MariaDB, to prove the pattern
generalizes rather than just querying our own database again.

PRODUCT_DATA_SOURCES below is the SECOND governance boundary, in
addition to the approval check: only a product listed here can ever be
queried for real data, no matter what a ticket says. This is intentional
defense-in-depth, not redundancy - a ticket could in principle be
approved for a product that was never wired to a real data source (the
other two catalog products in datahub_client.py aren't), and the
registry is what turns that into a clean 400 instead of an attempt to
resolve a WrenAI project that doesn't exist.
"""

import logging
from pathlib import Path
from typing import Any

from ..config import settings
from .llm_client import stream_chat_completion
from .wrenai_client import resolve_business_query

logger = logging.getLogger("dgo")

# product_id -> (WrenAI project path, schema description for the SQL
# prompt below). Schema text is hand-written to match
# wren/business_capacity_plan/models/*/metadata.yml exactly - kept as
# plain text here (not introspected from the MDL at runtime) since it
# also carries the same governed-engine guarantee wrenai_client.py
# already provides: even if this description drifted from the real
# schema, the worst case is the LLM writing SQL that the governed engine
# then rejects, not a wrong answer being returned as if correct.
PRODUCT_DATA_SOURCES: dict[str, dict[str, Any]] = {
    "customer-capacity-allocation": {
        "project_path": Path(settings.wren_business_project_path),
        "schema": """
    capacity_plan(id, customer_name, product_node, week_start, allocated_capacity, actual_wafer_starts, utilization_pct)
    customer_commitment(id, customer_name, commitment_quarter, committed_volume, confirmed_volume, status)
    wafer_start_actuals(id, lot_id, customer_name, product_node, start_date, wafer_count, fab_line)
    """.strip(),
    },
}


def build_business_sql_prompt(question: str, schema: str) -> str:
    """Mirrors chat.py's build_sql_prompt() shape (same "write one SELECT,
    NO_MATCH if nothing fits" contract), but against the real business
    schema above instead of the data_products catalog mirror."""
    return f"""
    You have a Postgres database with these tables and columns (all
    columns are their natural SQL types - dates are DATE, counts/volumes
    are integers, utilization_pct/committed figures are numeric):
    {schema}

    The user's question is: "{question}"

    Write ONE SQL SELECT statement that answers the question, using only
    the tables/columns above. Never write INSERT/UPDATE/DELETE/DDL - read
    only. Prefer aggregates (SUM/AVG/COUNT) with GROUP BY when the
    question asks for a summary rather than raw rows. Add a reasonable
    LIMIT (e.g. 50) if the question could otherwise return many rows.

    If the question cannot be answered from the tables/columns above,
    reply with exactly:
    NO_MATCH
    Reply with the SQL (or NO_MATCH) only - no explanation, no markdown
    code fences, no trailing semicolon.
    """


def _extract_sql(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
    return cleaned.strip().rstrip(";").strip()


class NoMatchingDataError(Exception):
    """Raised when the LLM determines the question can't be answered from
    the product's real schema - a legitimate "no" the caller should
    surface as such, not an integration failure."""


async def query_product_data(product_id: str, question: str) -> list[dict[str, Any]]:
    """Orchestrates: build a SQL prompt against the product's real schema,
    have the LLM write SQL, execute it through WrenAI's governed engine
    for that product's own WrenAI project. Callers (main.py) are
    responsible for the registry-membership and ticket-approval checks
    before calling this - this function assumes both already passed.

    Raises KeyError if product_id isn't in PRODUCT_DATA_SOURCES (callers
    should have already checked), NoMatchingDataError for a legitimate
    "the question doesn't fit this schema", and propagates any other
    exception (LLM unreachable, WrenAI/MDL unavailable, invalid SQL
    rejected by governance) for the caller to treat as an integration
    failure."""
    source = PRODUCT_DATA_SOURCES[product_id]
    prompt = build_business_sql_prompt(question, source["schema"])

    sql_reply = ""
    async for piece in stream_chat_completion(
        [{"role": "user", "content": prompt}],
        model=settings.llm_sql_model or None,
    ):
        sql_reply += piece
    sql = _extract_sql(sql_reply)
    logger.info("Business query for %s: question=%r sql=%r", product_id, question, sql)

    if not sql or sql.upper() == "NO_MATCH":
        raise NoMatchingDataError(question)

    return await resolve_business_query(sql, source["project_path"])
