import json

from app.config import settings
from app.integrations import camunda_client


def test_collection_variable_encoding():
    # Confirmed against a real local Camunda 7.22 instance: this exact
    # Object/ArrayList shape is required for a multi-instance collection
    # variable - a plain {"type": "Json", ...} raises InvalidRequestException.
    encoded = camunda_client._collection_variable(["a@example.com", "b@example.com"])
    assert encoded["type"] == "Object"
    assert encoded["valueInfo"] == {
        "objectTypeName": "java.util.ArrayList",
        "serializationDataFormat": "application/json",
    }
    assert json.loads(encoded["value"]) == ["a@example.com", "b@example.com"]


def test_auth_none_when_not_configured():
    assert camunda_client._auth() is None


def test_auth_set_when_username_and_password_configured(monkeypatch):
    monkeypatch.setattr(settings, "camunda_basic_auth_username", "user")
    monkeypatch.setattr(settings, "camunda_basic_auth_password", "pass")
    assert camunda_client._auth() is not None


async def test_start_approval_process_fails_gracefully_when_unreachable(monkeypatch):
    # Port 1 - nothing listens there.
    monkeypatch.setattr(settings, "camunda_base_url", "http://127.0.0.1:1/engine-rest")
    result = await camunda_client.start_approval_process("FAB-TEST", ["p1"], ["a@example.com"], "PoC")
    assert result.status.startswith("Skipped")
    assert result.process_instance_id is None


async def test_complete_approval_task_skips_when_no_process_instance():
    # No process_instance_id at all - e.g. Camunda was unreachable when
    # the ticket was created - must not raise, and must not attempt any
    # network call.
    status = await camunda_client.complete_approval_task(None, "a@example.com", "Approve", "")
    assert status.startswith("Skipped")


async def test_complete_approval_task_fails_gracefully_when_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "camunda_base_url", "http://127.0.0.1:1/engine-rest")
    status = await camunda_client.complete_approval_task("some-instance-id", "a@example.com", "Approve", "")
    assert status.startswith("Skipped")
