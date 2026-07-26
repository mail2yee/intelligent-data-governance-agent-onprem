"""
DataHub metadata catalog integration.

Confirmed against DataHub's own docs (docs.datahub.com):
  - GraphQL endpoint: POST {DATAHUB_API_URL}/api/graphql
  - Auth: personal access token as `Authorization: Bearer <token>`
  - Free-text dataset search: `search(input: { type: DATASET, query: "...", ... })`
  - Custom key/value properties on an entity: a `customProperties` field
    returning a list of `{ key value }` entries (this pattern was
    confirmed generically across entities; the exact nesting under the
    `Dataset` type specifically - i.e. whether it's `dataset.properties.customProperties`
    or `dataset.customProperties` directly - was NOT confirmed from the
    docs available. The query below assumes `properties.customProperties`
    (matching how `properties.name`/`properties.description` nest). If
    your instance's schema differs, adjust the query below - test it in
    your DataHub instance's GraphQL explorer (usually at
    `{DATAHUB_API_URL}/api/graphiql`) first.

Field mapping (confirmed with the user: maturity_level/data_quality_score/
etc. are assumed to live as DataHub customProperties, i.e. arbitrary
key/value pairs, not structured properties or glossary terms):
    owner, maturity_level, data_quality_score, frequency, tables_joined,
    db_type, db_host, db_port, db_schema
  are all read from customProperties by key name (see CUSTOM_PROPERTY_KEYS).
  If your org's DataHub uses different key names, adjust CUSTOM_PROPERTY_KEYS
  below rather than rewriting the query.

`id` (used throughout this app's routes/tickets/cart) isn't a DataHub
concept - DataHub identifies things by URN
(e.g. `urn:li:dataset:(urn:li:dataPlatform:postgres,foo.bar,PROD)`), not a
short slug. This maps each dataset's display name to a URL-safe slug for
`id` (see `_slugify`). Two datasets with the same name would collide -
fine for a small catalog, but revisit (e.g. hash the URN instead) if the
real catalog grows large enough for that to be likely.

Falls back to a hardcoded mock catalog (same shape) if DataHub is
unreachable, unauthenticated, or returns something unexpected - so the
rest of the app keeps working even before/if this is fully configured.
"""

import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger("dgo")

CUSTOM_PROPERTY_KEYS = {
    "owner": "owner",
    "maturity_level": "maturity_level",
    "data_quality_score": "data_quality_score",
    "frequency": "frequency",
    "tables_joined": "tables_joined",
    "db_type": "db_type",
    "db_host": "db_host",
    "db_port": "db_port",
    "db_schema": "db_schema",
}

SEARCH_QUERY = """
query listDatasets($query: String!) {
  search(input: { type: DATASET, query: $query, start: 0, count: 100 }) {
    searchResults {
      entity {
        urn
        ... on Dataset {
          properties {
            name
            description
            customProperties { key value }
          }
        }
      }
    }
  }
}
"""

MOCK_CATALOG = {
    "move-forecast-summary": {
        "id": "move-forecast-summary",
        "name": "FAB Production Move Forecast Summary",
        "description": "晶圓廠生產Move與 WIP 預估，跨設備機台(Bottleneck Tools)與派工系統整合之日彙整資料。用於預測出貨產能與達標率。",
        "owner": "fab_ops_owner@example.com",
        "maturity_level": "Gold",
        "data_quality_score": "98%",
        "frequency": "HOURLY",
        "tables_joined": "wip_moves, tool_bottleneck, dispatch_schedule",
        "db_type": "PostgreSQL",
        "db_host": "fab-ops-postgres.corp.internal",
        "db_port": "5432",
        "db_schema": "production_forecast",
    },
    "customer-demand-orders": {
        "id": "customer-demand-orders",
        "name": "Customer Demand Wafer Orders",
        "description": "全球客戶投片訂單與需求預測，包含Wafer數量、尺寸、承諾交期(Promised Date)與歷史Backlog。用於產銷平衡排程。",
        "owner": "sales_planning_owner@example.com",
        "maturity_level": "Silver",
        "data_quality_score": "92%",
        "frequency": "DAILY",
        "tables_joined": "customer_po, global_demand_forecast, sales_backlog",
        "db_type": "Oracle",
        "db_host": "sales-oracle-cluster.corp.internal",
        "db_port": "1521",
        "db_schema": "global_orders",
    },
    "customer-capacity-allocation": {
        "id": "customer-capacity-allocation",
        "name": "Specific Customer Capacity Allocation",
        "description": "為特定VIP客戶配置的晶圓代工產能(Allocated Capacity)，包含與預測需求(Forecast)之對比、實際投片承諾與Fab產能利用率。",
        "owner": "capacity_director@example.com",
        "maturity_level": "Gold",
        "data_quality_score": "99%",
        "frequency": "DAILY",
        "tables_joined": "capacity_plan, customer_commitment, wafer_start_actuals",
        "db_type": "PostgreSQL",
        "db_host": "capacity-postgres.corp.internal",
        "db_port": "5432",
        "db_schema": "capacity_mgmt",
    },
}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "dataset"


async def _fetch_from_datahub() -> dict:
    url = f"{settings.datahub_api_url}/api/graphql"
    headers = {"Content-Type": "application/json"}
    if settings.datahub_api_token:
        headers["Authorization"] = f"Bearer {settings.datahub_api_token}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers=headers,
            json={"query": SEARCH_QUERY, "variables": {"query": "*"}},
        )
        resp.raise_for_status()
        payload = resp.json()

    if payload.get("errors"):
        raise RuntimeError(f"DataHub GraphQL errors: {payload['errors']}")

    results = payload["data"]["search"]["searchResults"]
    catalog: dict = {}
    for result in results:
        entity = result.get("entity") or {}
        props = entity.get("properties") or {}
        name = props.get("name") or entity.get("urn", "unknown")
        custom = {p["key"]: p["value"] for p in (props.get("customProperties") or [])}

        product_id = _slugify(name)
        catalog[product_id] = {
            "id": product_id,
            "name": name,
            "description": props.get("description") or "",
            **{field: custom.get(key, "") for field, key in CUSTOM_PROPERTY_KEYS.items()},
        }
    return catalog


async def get_catalog() -> dict:
    try:
        catalog = await _fetch_from_datahub()
        if not catalog:
            raise RuntimeError("DataHub search returned zero datasets")
        logger.info("Loaded %d dataset(s) from DataHub", len(catalog))
        return catalog
    except Exception as e:
        logger.warning("DataHub fetch failed, falling back to mock catalog: %s", e)
        return MOCK_CATALOG
