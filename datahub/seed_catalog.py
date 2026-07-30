"""Seeds sample dataset entities into a local DataHub instance, matching the
exact shape `backend/app/integrations/datahub_client.py` expects to read back
(`properties.name`, `properties.description`, `properties.customProperties`
with the keys in CUSTOM_PROPERTY_KEYS) - so the app's real DataHub
integration can be exercised end-to-end locally instead of only ever hitting
its hardcoded MOCK_CATALOG fallback.

Confirmed working end-to-end 2026-07-30 against a local
`datahub docker quickstart` instance (v1.5.0.6): ingested these 3 datasets,
then hit `POST http://localhost:8080/api/graphql` with the app's own
SEARCH_QUERY and got them back with all customProperties intact.

Uses the `datahub` package's own Python emitter (acryl-datahub, already
installed on this machine as the `datahub` CLI's dependency) rather than a
YAML ingestion recipe - unlike the sibling agent_mem0_poc repo's business
glossary source (`datahub-business-glossary`), there's no source type that
natively expresses "dataset with arbitrary customProperties", so emitting
MetadataChangeProposals directly is the more direct route for this shape.

Usage:
    python3 datahub/seed_catalog.py
"""

from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import DatasetPropertiesClass

GMS_SERVER = "http://localhost:8080"

# DataHub platform names are lowercase, fixed identifiers (confirmed:
# "postgres", not "postgresql") - not necessarily identical to the db_type
# string this app displays in its own UI/mock catalog.
DB_TYPE_TO_PLATFORM = {
    "PostgreSQL": "postgres",
    "Oracle": "oracle",
}

# Same 3 example products as datahub_client.py's own MOCK_CATALOG fallback,
# so the DataHub-backed and mock paths are directly comparable in the UI.
CATALOG = {
    "move-forecast-summary": {
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


def main() -> None:
    emitter = DatahubRestEmitter(gms_server=GMS_SERVER)
    for product_id, item in CATALOG.items():
        platform = DB_TYPE_TO_PLATFORM[item["db_type"]]
        dataset_urn = make_dataset_urn(platform=platform, name=f"{item['db_schema']}.{product_id}", env="PROD")

        custom_properties = {k: v for k, v in item.items() if k not in ("name", "description")}
        dataset_properties = DatasetPropertiesClass(
            name=item["name"],
            description=item["description"],
            customProperties=custom_properties,
        )
        mcp = MetadataChangeProposalWrapper(entityUrn=dataset_urn, aspect=dataset_properties)
        emitter.emit(mcp)
        print(f"Seeded {dataset_urn}")

    print(f"\nDone. {len(CATALOG)} dataset(s) seeded to {GMS_SERVER}.")


if __name__ == "__main__":
    main()
