async def _mock_catalog(monkeypatch, catalog):
    async def _fake():
        return catalog

    monkeypatch.setattr("app.main.datahub_client.get_catalog", _fake)


async def _skip_camunda(monkeypatch):
    from app.integrations.camunda_client import ProcessStartResult

    async def _fake_start(*args, **kwargs):
        return ProcessStartResult("Skipped (test)", None)

    async def _fake_complete(*args, **kwargs):
        return "Skipped (test)"

    monkeypatch.setattr("app.main.camunda_client.start_approval_process", _fake_start)
    monkeypatch.setattr("app.main.camunda_client.complete_approval_task", _fake_complete)


async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_get_catalog(client, monkeypatch):
    # The route handler itself (app.main.get_catalog) had zero direct HTTP-
    # level coverage before this - every other test only exercises it as a
    # side effect of ticket creation, never GETs /api/catalog directly.
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "name": "Product One"}})
    res = await client.get("/api/catalog")
    assert res.status_code == 200
    assert res.json() == {"p1": {"id": "p1", "name": "Product One"}}


async def test_chat_endpoint_streams_sse(client, monkeypatch):
    # chat.py's run_chat() generator is unit-tested extensively elsewhere
    # (test_chat.py), but never before through the actual HTTP route -
    # this exercises app.main.chat()'s own logic: JSON body parsing, the
    # lang default, and the StreamingResponse/SSE headers.
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "name": "Product One"}})

    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog):
        captured["user_msg"] = user_msg
        captured["lang"] = lang
        captured["catalog"] = catalog
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    res = await client.post("/api/chat", json={"message": "hello there"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert '"reply": "ok"' in res.text
    assert captured["user_msg"] == "hello there"
    assert captured["lang"] == "zh"  # defaults to zh when "lang" is omitted
    assert captured["catalog"] == {"p1": {"id": "p1", "name": "Product One"}}


async def test_chat_endpoint_respects_explicit_en_lang(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog):
        captured["lang"] = lang
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi", "lang": "en"})
    assert captured["lang"] == "en"


async def test_create_and_list_ticket(client, monkeypatch):
    await _mock_catalog(
        monkeypatch,
        {
            "customer-capacity-allocation": {
                "id": "customer-capacity-allocation",
                "owner": "capacity_director@example.com",
            }
        },
    )
    await _skip_camunda(monkeypatch)

    res = await client.post(
        "/api/tickets",
        json={"products": ["customer-capacity-allocation"], "objective": "test", "purpose": "PoC"},
    )
    assert res.status_code == 200
    ticket_id = res.json()["ticket_id"]
    assert ticket_id.startswith("FAB-")

    tickets = (await client.get("/api/tickets")).json()
    assert len(tickets) == 1
    ticket = tickets[0]
    assert ticket["id"] == ticket_id
    assert ticket["status"] == "PENDING_APPROVAL"
    # padded up to 3 with the configured fallback approvers
    assert len(ticket["owners"]) == 3
    assert "capacity_director@example.com" in ticket["owners"]
    assert all(a["decision"] == "PENDING" for a in ticket["approvals"].values())


async def test_ticket_stores_camunda_process_instance_id_and_completes_task_on_approval(client, monkeypatch):
    # Confirms the two new integration points added alongside the
    # Camunda 7 rewrite: create_ticket persists whatever process_instance_id
    # Camunda returned (needed later to find the right task), and
    # submit_approval passes that same id through to complete_approval_task.
    from app.integrations.camunda_client import ProcessStartResult

    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})

    async def _fake_start(*args, **kwargs):
        return ProcessStartResult("Successfully triggered in Camunda", "process-instance-123")

    monkeypatch.setattr("app.main.camunda_client.start_approval_process", _fake_start)

    completed_with = {}

    async def _fake_complete(process_instance_id, owner_email, decision, reason):
        completed_with["process_instance_id"] = process_instance_id
        completed_with["owner_email"] = owner_email
        completed_with["decision"] = decision
        return "Completed in Camunda"

    monkeypatch.setattr("app.main.camunda_client.complete_approval_task", _fake_complete)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]

    await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={"owner_email": "a@example.com", "decision": "Approve", "reason": ""},
    )

    assert completed_with == {
        "process_instance_id": "process-instance-123",
        "owner_email": "a@example.com",
        "decision": "Approve",
    }


async def test_approve_all_owners_moves_ticket_to_approved(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]

    for owner in owners:
        res = await client.post(
            f"/api/tickets/{ticket_id}/approvals",
            json={"owner_email": owner, "decision": "Approve", "reason": ""},
        )
        assert res.status_code == 200

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "APPROVED"
    for approval in ticket["approvals"].values():
        assert approval["decision"] == "Approve"
        assert approval["cycle_time_seconds"] is not None


async def test_partial_approval_stays_pending(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]

    await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={"owner_email": owners[0], "decision": "Approve", "reason": ""},
    )

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "PENDING_APPROVAL"


async def test_reject_moves_ticket_to_rejected_even_if_others_still_pending(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]

    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={"owner_email": owners[0], "decision": "Reject", "reason": "not needed"},
    )
    assert res.status_code == 200

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "REJECTED"
    assert ticket["approvals"][owners[0]]["reason"] == "not needed"


async def test_approval_on_unknown_ticket_returns_404(client):
    res = await client.post(
        "/api/tickets/FAB-DOESNOTEXIST/approvals",
        json={"owner_email": "a@example.com", "decision": "Approve", "reason": ""},
    )
    assert res.status_code == 404


async def test_approval_from_non_owner_returns_404(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]

    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={"owner_email": "not-an-owner@example.com", "decision": "Approve", "reason": ""},
    )
    assert res.status_code == 404


async def test_connection_meta_unknown_product_returns_404(client):
    res = await client.get("/api/catalog/does-not-exist/connection")
    assert res.status_code == 404


async def test_connection_meta_known_product(client, monkeypatch):
    await _mock_catalog(
        monkeypatch,
        {"p1": {"id": "p1", "db_type": "PostgreSQL", "db_host": "h", "db_port": "5432", "db_schema": "s"}},
    )
    res = await client.get("/api/catalog/p1/connection")
    assert res.status_code == 200
    assert res.json() == {"db_type": "PostgreSQL", "db_host": "h", "db_port": "5432", "db_schema": "s"}
