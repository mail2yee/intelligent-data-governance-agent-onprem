from app.config import settings


async def test_api_routes_open_when_api_key_not_configured(client):
    # Default/dev behavior - matches every other optional integration in
    # this repo (empty setting = disabled).
    res = await client.get("/api/tickets")
    assert res.status_code == 200


async def test_api_route_rejects_missing_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")
    res = await client.get("/api/tickets")
    assert res.status_code == 401


async def test_api_route_rejects_wrong_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")
    res = await client.get("/api/tickets", headers={"X-API-Key": "wrong"})
    assert res.status_code == 401


async def test_api_route_accepts_correct_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")
    res = await client.get("/api/tickets", headers={"X-API-Key": "secret123"})
    assert res.status_code == 200


async def test_health_never_requires_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")
    res = await client.get("/health")
    assert res.status_code == 200
