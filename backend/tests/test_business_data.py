import pytest

from app.integrations import business_data
from app.integrations.business_data import (
    NoMatchingDataError,
    build_business_sql_prompt,
    query_product_data,
)

SCHEMA = "capacity_plan(id, customer_name)"


def test_build_business_sql_prompt_includes_schema_and_question():
    prompt = build_business_sql_prompt("how much capacity for Acme?", SCHEMA)
    assert SCHEMA in prompt
    assert "how much capacity for Acme?" in prompt
    assert "NO_MATCH" in prompt


async def test_query_product_data_raises_no_matching_data_on_no_match(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "NO_MATCH"

    monkeypatch.setattr("app.integrations.business_data.stream_chat_completion", _fake_stream)

    with pytest.raises(NoMatchingDataError):
        await query_product_data("customer-capacity-allocation", "unrelated question")


async def test_query_product_data_raises_no_matching_data_on_empty_reply(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "   "

    monkeypatch.setattr("app.integrations.business_data.stream_chat_completion", _fake_stream)

    with pytest.raises(NoMatchingDataError):
        await query_product_data("customer-capacity-allocation", "unrelated question")


async def test_query_product_data_executes_generated_sql_against_correct_project(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "SELECT customer_name FROM capacity_plan"

    monkeypatch.setattr("app.integrations.business_data.stream_chat_completion", _fake_stream)

    captured = {}

    async def _fake_resolve(sql, project_path):
        captured["sql"] = sql
        captured["project_path"] = project_path
        return [{"customer_name": "Acme Semiconductor"}]

    monkeypatch.setattr("app.integrations.business_data.resolve_business_query", _fake_resolve)

    rows = await query_product_data("customer-capacity-allocation", "which customers?")

    assert rows == [{"customer_name": "Acme Semiconductor"}]
    assert captured["sql"] == "SELECT customer_name FROM capacity_plan"
    assert captured["project_path"] == business_data.PRODUCT_DATA_SOURCES[
        "customer-capacity-allocation"
    ]["project_path"]


async def test_query_product_data_strips_markdown_fences_from_sql(monkeypatch):
    async def _fake_stream(messages, model=None):
        yield "```sql\nSELECT customer_name FROM capacity_plan;\n```"

    monkeypatch.setattr("app.integrations.business_data.stream_chat_completion", _fake_stream)

    captured = {}

    async def _fake_resolve(sql, project_path):
        captured["sql"] = sql
        return []

    monkeypatch.setattr("app.integrations.business_data.resolve_business_query", _fake_resolve)

    await query_product_data("customer-capacity-allocation", "which customers?")
    assert captured["sql"] == "SELECT customer_name FROM capacity_plan"
