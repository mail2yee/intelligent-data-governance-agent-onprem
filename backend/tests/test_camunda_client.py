from app.config import settings
from app.integrations import camunda_client


def test_oauth_not_configured_by_default():
    assert camunda_client._oauth_configured() is False


def test_oauth_configured_when_all_three_set(monkeypatch):
    monkeypatch.setattr(settings, "camunda_oauth_client_id", "id")
    monkeypatch.setattr(settings, "camunda_oauth_client_secret", "secret")
    monkeypatch.setattr(settings, "camunda_oauth_token_url", "https://example.com/token")
    assert camunda_client._oauth_configured() is True


def test_oauth_not_configured_when_only_partially_set(monkeypatch):
    monkeypatch.setattr(settings, "camunda_oauth_client_id", "id")
    monkeypatch.setattr(settings, "camunda_oauth_client_secret", "")
    monkeypatch.setattr(settings, "camunda_oauth_token_url", "")
    assert camunda_client._oauth_configured() is False


async def test_start_approval_process_fails_gracefully_when_gateway_unreachable(monkeypatch):
    # Port 1 - nothing listens there. Confirms a "Skipped" status comes
    # back instead of an unhandled exception breaking ticket creation.
    monkeypatch.setattr(settings, "camunda_gateway_address", "127.0.0.1:1")
    status = await camunda_client.start_approval_process("FAB-TEST", ["p1"], ["a@example.com"], "PoC")
    assert status.startswith("Skipped")
