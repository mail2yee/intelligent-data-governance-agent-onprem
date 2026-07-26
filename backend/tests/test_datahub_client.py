import httpx
import pytest

from app.integrations.datahub_client import MOCK_CATALOG, _slugify, get_catalog


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("FAB Production Move Forecast Summary", "fab-production-move-forecast-summary"),
        ("Customer Demand Wafer Orders!", "customer-demand-wafer-orders"),
        ("  weird   spacing  ", "weird-spacing"),
        ("", "dataset"),
    ],
)
def test_slugify(name, expected):
    assert _slugify(name) == expected


async def test_get_catalog_falls_back_to_mock_when_unreachable(monkeypatch):
    async def _boom():
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.integrations.datahub_client._fetch_from_datahub", _boom)

    catalog = await get_catalog()
    assert catalog == MOCK_CATALOG


async def test_get_catalog_falls_back_to_mock_when_empty(monkeypatch):
    async def _empty():
        return {}

    monkeypatch.setattr("app.integrations.datahub_client._fetch_from_datahub", _empty)

    catalog = await get_catalog()
    assert catalog == MOCK_CATALOG


async def test_get_catalog_uses_real_data_when_available(monkeypatch):
    fake = {"foo-bar": {"id": "foo-bar", "name": "Foo Bar"}}

    async def _fake():
        return fake

    monkeypatch.setattr("app.integrations.datahub_client._fetch_from_datahub", _fake)

    catalog = await get_catalog()
    assert catalog == fake
