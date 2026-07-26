import pytest

from app.db import DataProduct, async_session
from app.integrations import wrenai_client

CATALOG = {
    "customer-capacity-allocation": {
        "name": "Specific Customer Capacity Allocation",
        "description": "VIP customer capacity",
        "owner": "capacity_director@example.com",
        "maturity_level": "Gold",
        "data_quality_score": "99%",
        "frequency": "DAILY",
        "tables_joined": "capacity_plan",
        "db_type": "PostgreSQL",
        "db_host": "capacity-postgres.corp.internal",
        "db_port": "5432",
        "db_schema": "capacity_mgmt",
    },
    "move-forecast-summary": {
        "name": "FAB Production Move Forecast Summary",
        "maturity_level": "Gold",
    },
}


async def _all_products() -> dict[str, DataProduct]:
    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(DataProduct))
        return {p.id: p for p in result.scalars().all()}


async def test_sync_catalog_inserts_rows():
    await wrenai_client.sync_catalog(CATALOG)
    rows = await _all_products()
    assert set(rows) == set(CATALOG)
    assert rows["customer-capacity-allocation"].owner == "capacity_director@example.com"
    # Fields missing from the catalog item default to "" rather than erroring.
    assert rows["move-forecast-summary"].owner == ""


async def test_sync_catalog_updates_existing_and_removes_stale_rows():
    await wrenai_client.sync_catalog(CATALOG)

    updated = {
        "customer-capacity-allocation": {
            **CATALOG["customer-capacity-allocation"],
            "data_quality_score": "100%",
        },
    }
    await wrenai_client.sync_catalog(updated)

    rows = await _all_products()
    assert set(rows) == {"customer-capacity-allocation"}  # move-forecast-summary dropped
    assert rows["customer-capacity-allocation"].data_quality_score == "100%"


async def test_resolve_matches_raises_when_mdl_not_built():
    # No `wren context build` has run in this test environment (that only
    # happens via backend/entrypoint.sh in Docker) - confirms this fails
    # loudly rather than silently, so chat.py's caller can fall back.
    with pytest.raises(Exception):  # noqa: B017 - exact exception type is wrenai's, not ours to pin down
        await wrenai_client.resolve_matches("SELECT id FROM data_products")
