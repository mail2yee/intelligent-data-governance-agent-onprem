"""
WrenAI semantic-layer integration for zero-hallucination data-subject
matching.

Confirmed by actually installing wrenai (0.13.1) locally and smoke-testing
it (2026-07): as of WrenAI's 2026-05-07 architecture change, the old
"docker-compose service with a REST/GraphQL API" shape (now called Wren
GenBI Classic, frozen on the upstream repo's `legacy/v1` branch) is
retired. Current WrenAI is a plain Python package imported directly -
`wren.engine.WrenEngine` executes SQL through a governed engine that
rejects any column/table not declared in the semantic model (MDL, see
../../../wren/project/), rather than WrenAI itself doing NL -> SQL for us.
This mirrors the pattern already proven end-to-end (real Postgres, real
governance rejections observed) in the sibling agent_mem0_poc repo's
memory-api/wren_client.py - this module is deliberately close to that one.

How this is used here: chat.py has our own on-prem LLM write a SQL SELECT
against the `data_products` table (kept in sync with the DataHub catalog,
see sync_catalog() below) using the field names declared in the MDL. This
module executes that SQL through the governed engine - only rows that
structurally exist can come back, which is a stronger zero-hallucination
guarantee than pattern-matching free-form LLM prose (the previous
approach, kept in chat.py as a fallback for when this integration itself
fails).

Deliberately not using the `wren-pydantic` package, same reasoning as the
PoC: it pulls in all of `pydantic-ai`'s provider extras for one query()
method we don't need - `wren.engine` + `wren.profile` directly is enough.

One WrenAI project = one physical data source connection (confirmed via
the PoC's testing) - it cannot itself join across the different databases
DataHub's catalog entries actually live in (see each entry's db_host/
db_type). That's why this models the *catalog* (our own Postgres mirror
of it) rather than the underlying business databases - this integration
answers "which data subject matches this need", not "run this analytical
query against the real data", which is deliberately out of scope (see
HANDOFF.md's semantic layer notes).

UNCONFIRMED against this repo's actual Docker Compose stack end-to-end -
smoke-tested locally against a throwaway DuckDB table and a real `wren
context build`, not yet run inside a container here. In particular,
`resolve_profile_for_project()` depends on `wren profile add` having
already run (see backend/entrypoint.sh) - if that hasn't happened (e.g.
running tests, or local dev without the Docker entrypoint), calls here
raise, which callers should treat like any other integration failure.
"""

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

import opencc
from sqlalchemy import select
from wren.engine import WrenEngine
from wren.profile import expand_profile_secrets, resolve_profile_for_project

from ..config import settings
from ..db import DataProduct, async_session

logger = logging.getLogger("dgo")

WREN_PROJECT_PATH = Path(settings.wren_project_path)
_MDL_PATH = WREN_PROJECT_PATH / "target" / "mdl.json"

# Columns copied from a DataHub catalog entry into our data_products
# mirror table - keep in sync with wren/project/models/data_products/
# metadata.yml and db.py's DataProduct model.
_CATALOG_FIELDS = (
    "name",
    "description",
    "owner",
    "maturity_level",
    "data_quality_score",
    "frequency",
    "tables_joined",
    "db_type",
    "db_host",
    "db_port",
    "db_schema",
)

# Fields folded into search_text (see _search_text below) - deliberately
# narrower than _CATALOG_FIELDS, just the columns worth free-text matching
# against.
_SEARCHABLE_FIELDS = ("name", "description", "tables_joined")

_TRADITIONAL_TO_SIMPLIFIED = opencc.OpenCC("t2s")


def _field(item: dict, field: str) -> str:
    """`item.get(field, "")` alone isn't enough: the default only kicks in
    when the key is *missing*, not when it's present with value None (a
    real possibility once this reads from actual DataHub customProperties
    instead of the hardcoded mock catalog, where an unset optional field
    is plausibly None rather than absent) - `str(None)` silently produces
    the literal text "None", which would pollute search_text and any
    ILIKE match against it."""
    return str(item.get(field) or "")


def _search_text(item: dict) -> str:
    """Traditional-Chinese catalog text, plus a Simplified-Chinese copy of
    the same text, concatenated - confirmed via local testing that a small
    LLM asked to write SQL sometimes extracts a Simplified-Chinese keyword
    for a Traditional-Chinese request (or vice versa), and plain ILIKE does
    no script folding, so a keyword in either script needs to be able to
    hit this column regardless of which script the source data is in."""
    original = " ".join(_field(item, field) for field in _SEARCHABLE_FIELDS)
    return f"{original} {_TRADITIONAL_TO_SIMPLIFIED.convert(original)}"


async def sync_catalog(catalog: dict) -> None:
    """Upsert the current DataHub catalog into our own `data_products`
    table, so WrenAI's governed engine - which needs a live connected
    data source, not a Python dict - has something real to validate SQL
    against. Portable insert/update/delete rather than a dialect-specific
    ON CONFLICT, since tests run against SQLite but production is
    Postgres."""
    async with async_session() as session:
        existing = {p.id: p for p in (await session.execute(select(DataProduct))).scalars().all()}
        seen: set[str] = set()
        for product_id, item in catalog.items():
            seen.add(product_id)
            values = {field: _field(item, field) for field in _CATALOG_FIELDS}
            values["search_text"] = _search_text(item)
            if product_id in existing:
                for field, value in values.items():
                    setattr(existing[product_id], field, value)
            else:
                session.add(DataProduct(id=product_id, **values))
        for product_id, row in existing.items():
            if product_id not in seen:
                await session.delete(row)
        await session.commit()


def _build_engine() -> WrenEngine:
    manifest = json.loads(_MDL_PATH.read_text(encoding="utf-8"))
    manifest_str = base64.b64encode(json.dumps(manifest).encode("utf-8")).decode()

    _, profile = resolve_profile_for_project(WREN_PROJECT_PATH)
    profile = expand_profile_secrets(profile)
    data_source = profile.pop("datasource")

    return WrenEngine(manifest_str=manifest_str, data_source=data_source, connection_info=profile)


def _execute_sql(sql: str) -> list[dict[str, Any]]:
    table = _build_engine().query(sql)
    return table.to_pylist()


async def resolve_matches(sql: str) -> list[dict[str, Any]]:
    """Execute agent-written SQL against the data_products semantic model
    through WrenAI's governed engine (blocking call, run off the event
    loop). Raises if the query is invalid or references anything outside
    the declared MDL - callers should treat that the same as any other
    integration failure in this app (see chat.py's fallback chain)."""
    return await asyncio.to_thread(_execute_sql, sql)
