"""
DataHub metadata catalog integration - STUB, not wired yet.

Need before implementing for real: the DataHub instance's GMS endpoint
URL and an auth token (DATAHUB_API_URL / DATAHUB_API_TOKEN in .env are
placeholders). DataHub's GraphQL API is the usual way to pull dataset
metadata (name, description, owners, glossary terms, etc.) - map that
response shape onto the fields the frontend expects (see the
`id`/`name`/`description`/`owner`/`maturity_level`/`data_quality_score`/
`frequency`/`tables_joined` fields used below and by the GCP PoC's
LOCAL_CATALOG, which this mock mirrors).

The db_type/db_host/db_port/db_schema fields back the "connection code"
feature in the UI (a generated Python/Java snippet showing how to reach
the underlying database) - DataHub can supply these too, typically via
a custom dataset property or a linked "Data Platform Instance".

Until this is wired, `get_catalog()` returns this same hardcoded mock
data so the rest of the app (search, cards, tickets) has something real
to develop against.
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


async def get_catalog() -> dict:
    """TODO: replace with a real DataHub GraphQL query once the instance
    URL and token are confirmed."""
    return MOCK_CATALOG
