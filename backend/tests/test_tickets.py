async def _mock_catalog(monkeypatch, catalog):
    async def _fake():
        return catalog

    monkeypatch.setattr("app.main.datahub_client.get_catalog", _fake)


async def _skip_camunda(monkeypatch):
    async def _fake(*args, **kwargs):
        return "Skipped (test)"

    monkeypatch.setattr("app.main.camunda_client.start_approval_process", _fake)


async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


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
