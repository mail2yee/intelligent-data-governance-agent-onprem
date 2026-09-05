async def _mock_catalog(monkeypatch, catalog):
    async def _fake():
        return catalog

    monkeypatch.setattr("app.main.datahub_client.get_catalog", _fake)


def _approval_payload(owner_email, decision, reason=""):
    # user_key/user_token: identity.py's trust-on-first-use gate now
    # requires submit_approval's caller to prove ownership of
    # owner_email - using owner_email itself as the user_key keeps
    # these tests' existing "approve as this owner" shape intact, one
    # deterministic fake token per owner is enough for TOFU to accept it.
    return {
        "owner_email": owner_email,
        "decision": decision,
        "reason": reason,
        "user_key": owner_email,
        "user_token": f"test-token-{owner_email}",
    }


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

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["user_msg"] = user_msg
        captured["lang"] = lang
        captured["catalog"] = catalog
        captured["mode"] = mode
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    res = await client.post("/api/chat", json={"message": "hello there"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert '"reply": "ok"' in res.text
    assert captured["user_msg"] == "hello there"
    assert captured["lang"] == "zh"  # defaults to zh when "lang" is omitted
    assert captured["catalog"] == {"p1": {"id": "p1", "name": "Product One"}}
    assert captured["mode"] == "ai"  # defaults to ai when "mode" is omitted


async def test_chat_endpoint_respects_explicit_en_lang(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["lang"] = lang
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi", "lang": "en"})
    assert captured["lang"] == "en"


async def test_chat_endpoint_passes_keyword_mode_through(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["mode"] = mode
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi", "mode": "keyword"})
    assert captured["mode"] == "keyword"


async def test_chat_endpoint_ignores_unknown_mode_value(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["mode"] = mode
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi", "mode": "bogus"})
    assert captured["mode"] == "ai"


async def test_chat_endpoint_passes_history_through(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["history"] = history
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post(
        "/api/chat",
        json={
            "message": "產能面的",
            "history": [
                {"role": "user", "content": "我想要做一個 report"},
                {"role": "assistant", "content": "可以說明一下想分析的報表主要跟哪個方向有關嗎？"},
            ],
        },
    )
    assert captured["history"] == [
        {"role": "user", "content": "我想要做一個 report"},
        {"role": "assistant", "content": "可以說明一下想分析的報表主要跟哪個方向有關嗎？"},
    ]


async def test_chat_endpoint_passes_user_key_and_fetched_preferences_to_run_chat(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    from app import preferences as preferences_mod

    await preferences_mod._save_preferences("tim@example.com", ["usually asks about capacity data"])

    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["user_key"] = user_key
        captured["preferences"] = preferences
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post(
        "/api/chat", json={"message": "hi", "user_key": "tim@example.com", "user_token": "tim-token"}
    )
    assert captured["user_key"] == "tim@example.com"
    assert captured["preferences"] == ["usually asks about capacity data"]


async def test_chat_endpoint_without_user_key_passes_none_preferences(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["user_key"] = user_key
        captured["preferences"] = preferences
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi"})
    assert captured["user_key"] is None
    assert captured["preferences"] is None


async def test_chat_endpoint_strips_and_caps_user_key(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["user_key"] = user_key
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post(
        "/api/chat",
        json={"message": "hi", "user_key": "  padded@example.com  ", "user_token": "padded-token"},
    )
    assert captured["user_key"] == "padded@example.com"

    await client.post("/api/chat", json={"message": "hi", "user_key": "   "})
    assert captured["user_key"] is None


async def test_get_preferences_returns_saved_list(client, monkeypatch):
    from app import preferences as preferences_mod

    await preferences_mod._save_preferences("tim@example.com", ["usually asks about capacity data"])
    res = await client.get("/api/preferences/tim@example.com", headers={"X-User-Token": "tim-token"})
    assert res.status_code == 200
    assert res.json() == {"preferences": ["usually asks about capacity data"]}


async def test_get_preferences_empty_for_unknown_user(client):
    res = await client.get("/api/preferences/nobody@example.com", headers={"X-User-Token": "nobody-token"})
    assert res.status_code == 200
    assert res.json() == {"preferences": []}


async def test_delete_preferences_clears_list(client, monkeypatch):
    from app import preferences as preferences_mod

    await preferences_mod._save_preferences("tim@example.com", ["usually asks about capacity data"])
    res = await client.delete("/api/preferences/tim@example.com", headers={"X-User-Token": "tim-token"})
    assert res.status_code == 200
    assert res.json() == {"status": "success"}

    res = await client.get("/api/preferences/tim@example.com", headers={"X-User-Token": "tim-token"})
    assert res.json() == {"preferences": []}


async def test_chat_endpoint_defaults_history_to_empty_list(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["history"] = history
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post("/api/chat", json={"message": "hi"})
    assert captured["history"] == []


async def test_chat_endpoint_drops_malformed_history_entries(client, monkeypatch):
    # Client-controlled input reaching an LLM prompt - malformed entries
    # (wrong role, missing content, not even a dict) must be dropped
    # rather than passed through as-is or crashing the request.
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["history"] = history
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    await client.post(
        "/api/chat",
        json={
            "message": "hi",
            "history": [
                {"role": "user", "content": "kept"},
                {"role": "system", "content": "dropped - not user/assistant"},
                {"role": "user", "content": ""},  # dropped - empty content
                {"role": "assistant"},  # dropped - no content key at all
                "not even a dict",  # dropped
            ],
        },
    )
    assert captured["history"] == [{"role": "user", "content": "kept"}]


async def test_chat_endpoint_caps_history_length_and_turn_size(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})
    captured = {}

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        captured["history"] = history
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    long_history = [{"role": "user", "content": f"turn {i}"} for i in range(10)]
    long_history.append({"role": "user", "content": "x" * 3000})

    await client.post("/api/chat", json={"message": "hi", "history": long_history})
    assert len(captured["history"]) == 6  # last 6 turns only
    assert len(captured["history"][-1]["content"]) == 2000  # truncated per-turn


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
        json=_approval_payload("a@example.com", "Approve"),
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
            json=_approval_payload(owner, "Approve"),
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
        json=_approval_payload(owners[0], "Approve"),
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
        json=_approval_payload(owners[0], "Reject", "not needed"),
    )
    assert res.status_code == 200

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "REJECTED"
    assert ticket["approvals"][owners[0]]["reason"] == "not needed"


async def test_approval_on_unknown_ticket_returns_404(client):
    res = await client.post(
        "/api/tickets/FAB-DOESNOTEXIST/approvals",
        json=_approval_payload("a@example.com", "Approve"),
    )
    assert res.status_code == 404


async def test_approval_from_non_owner_returns_404(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)

    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]

    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json=_approval_payload("not-an-owner@example.com", "Approve"),
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


# --- POST /api/catalog/{product_id}/query -----------------------------
# Two independent server-side gates (see main.py's query_product_data()
# docstring and business_data.py's module docstring): registry
# membership and an APPROVED ticket that actually covers the product.
# "customer-capacity-allocation" is the one real entry in
# business_data.PRODUCT_DATA_SOURCES - used below as the "wired" product;
# any other id exercises the "not wired" 400.


async def _approve_ticket_for(client, monkeypatch, product_id, owner="a@example.com"):
    await _mock_catalog(monkeypatch, {product_id: {"id": product_id, "owner": owner}})
    await _skip_camunda(monkeypatch)
    res = await client.post(
        "/api/tickets", json={"products": [product_id], "objective": "t", "purpose": "PoC"}
    )
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]
    for o in owners:
        await client.post(
            f"/api/tickets/{ticket_id}/approvals",
            json=_approval_payload(o, "Approve"),
        )
    return ticket_id


async def test_query_unwired_product_returns_400(client):
    res = await client.post("/api/catalog/move-forecast-summary/query", json={"question": "x"})
    assert res.status_code == 400


async def test_query_wired_product_without_approved_ticket_returns_403(client):
    res = await client.post(
        "/api/catalog/customer-capacity-allocation/query", json={"question": "which customers?"}
    )
    assert res.status_code == 403


async def test_query_missing_question_returns_400(client, monkeypatch):
    await _approve_ticket_for(client, monkeypatch, "customer-capacity-allocation")
    res = await client.post("/api/catalog/customer-capacity-allocation/query", json={"question": "  "})
    assert res.status_code == 400


async def test_query_with_approved_ticket_returns_rows(client, monkeypatch):
    await _approve_ticket_for(client, monkeypatch, "customer-capacity-allocation")

    async def _fake_query(product_id, question):
        assert product_id == "customer-capacity-allocation"
        assert question == "which customers?"
        return [{"customer_name": "Acme Semiconductor"}]

    monkeypatch.setattr("app.main.business_data.query_product_data", _fake_query)

    res = await client.post(
        "/api/catalog/customer-capacity-allocation/query", json={"question": "which customers?"}
    )
    assert res.status_code == 200
    assert res.json() == {"rows": [{"customer_name": "Acme Semiconductor"}]}


async def test_query_returns_empty_rows_on_no_matching_data(client, monkeypatch):
    await _approve_ticket_for(client, monkeypatch, "customer-capacity-allocation")

    from app.integrations.business_data import NoMatchingDataError

    async def _fake_query(product_id, question):
        raise NoMatchingDataError(question)

    monkeypatch.setattr("app.main.business_data.query_product_data", _fake_query)

    res = await client.post(
        "/api/catalog/customer-capacity-allocation/query", json={"question": "weather today?"}
    )
    assert res.status_code == 200
    assert res.json()["rows"] == []


# --- Identity/ownership enforcement (2026-09-05 security fixes) ------
# See identity.py's module docstring: trust-on-first-use, not real
# authentication, but it does mean once a user_key is claimed by one
# token, a different token can never act as that user_key again.


async def test_submit_approval_rejects_decision_not_in_allowed_set(client, monkeypatch):
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)
    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]

    # Lowercase "reject" previously fell through the `"Reject" in states`
    # check and silently became a completed (non-pending) approval -
    # exactly the "reject laundered into an approve" bug the review found.
    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json=_approval_payload("a@example.com", "reject"),
    )
    assert res.status_code == 400

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "PENDING_APPROVAL"  # never touched


async def test_submit_approval_rejects_mismatched_user_key(client, monkeypatch):
    # user_key must equal owner_email - can't submit a decision "as"
    # someone else even with a validly-claimed identity of your own.
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)
    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]

    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={
            "owner_email": "a@example.com",
            "decision": "Approve",
            "reason": "",
            "user_key": "attacker@example.com",
            "user_token": "attackers-own-token",
        },
    )
    assert res.status_code == 403

    ticket = (await client.get("/api/tickets")).json()[0]
    assert ticket["status"] == "PENDING_APPROVAL"


async def test_submit_approval_rejects_a_token_that_does_not_match_the_owners_claimed_token(client, monkeypatch):
    # This is the exploit chain the security review found: create a
    # ticket, read the owner list via GET /api/tickets (public), then
    # try to approve as that owner. Once the real owner has claimed
    # their user_key with their own token, a second caller presenting a
    # different token for the same user_key must be rejected.
    await _mock_catalog(monkeypatch, {"p1": {"id": "p1", "owner": "a@example.com"}})
    await _skip_camunda(monkeypatch)
    res = await client.post("/api/tickets", json={"products": ["p1"], "objective": "t", "purpose": "PoC"})
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]
    assert "a@example.com" in owners  # confirms the owner list really is readable

    # The real owner claims their identity first.
    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json=_approval_payload("a@example.com", "Approve"),
    )
    assert res.status_code == 200

    # An "attacker" who only knows the email from the owner list above -
    # not the real owner's token - tries to flip the decision.
    res = await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json={
            "owner_email": "a@example.com",
            "decision": "Reject",
            "reason": "attacker",
            "user_key": "a@example.com",
            "user_token": "a-guessed-or-different-token",
        },
    )
    assert res.status_code == 403


async def test_chat_endpoint_rejects_mismatched_token_for_claimed_user_key(client, monkeypatch):
    await _mock_catalog(monkeypatch, {})

    async def _fake_run_chat(user_msg, lang, catalog, mode, history=None, user_key=None, preferences=None):
        yield 'data: {"type": "final", "reply": "ok", "matched_products": []}\n\n'

    monkeypatch.setattr("app.main.run_chat", _fake_run_chat)

    res = await client.post(
        "/api/chat", json={"message": "hi", "user_key": "tim@example.com", "user_token": "tims-token"}
    )
    assert res.status_code == 200

    res = await client.post(
        "/api/chat", json={"message": "hi", "user_key": "tim@example.com", "user_token": "wrong-token"}
    )
    assert res.status_code == 403


async def test_get_preferences_requires_matching_token(client, monkeypatch):
    from app import preferences as preferences_mod

    await preferences_mod._save_preferences("tim@example.com", ["usually asks about capacity data"])

    # No token header at all - an empty token is never valid, even
    # against a user_key nobody has claimed yet (TOFU only ever claims
    # on a real, non-empty token).
    res = await client.get("/api/preferences/tim@example.com")
    assert res.status_code == 403

    # First real, non-empty token establishes the claim.
    res = await client.get("/api/preferences/tim@example.com", headers={"X-User-Token": "tims-real-token"})
    assert res.status_code == 200

    # A different token can no longer read it.
    res = await client.get(
        "/api/preferences/tim@example.com", headers={"X-User-Token": "not-tims-token"}
    )
    assert res.status_code == 403


async def test_delete_preferences_requires_matching_token(client, monkeypatch):
    from app import preferences as preferences_mod

    await preferences_mod._save_preferences("tim@example.com", ["usually asks about capacity data"])
    # Establish the real claim first, exactly as get_preferences_returns_saved_list does.
    await client.get("/api/preferences/tim@example.com", headers={"X-User-Token": "tim-token"})

    res = await client.delete(
        "/api/preferences/tim@example.com", headers={"X-User-Token": "not-tims-token"}
    )
    assert res.status_code == 403

    # Preference survives the rejected delete attempt.
    res = await client.get("/api/preferences/tim@example.com", headers={"X-User-Token": "tim-token"})
    assert res.json() == {"preferences": ["usually asks about capacity data"]}


async def test_query_rejected_ticket_does_not_grant_access(client, monkeypatch):
    await _mock_catalog(
        monkeypatch, {"customer-capacity-allocation": {"id": "customer-capacity-allocation", "owner": "a@example.com"}}
    )
    await _skip_camunda(monkeypatch)
    res = await client.post(
        "/api/tickets",
        json={"products": ["customer-capacity-allocation"], "objective": "t", "purpose": "PoC"},
    )
    ticket_id = res.json()["ticket_id"]
    owners = (await client.get("/api/tickets")).json()[0]["owners"]
    await client.post(
        f"/api/tickets/{ticket_id}/approvals",
        json=_approval_payload(owners[0], "Reject", "no"),
    )

    res = await client.post(
        "/api/catalog/customer-capacity-allocation/query", json={"question": "which customers?"}
    )
    assert res.status_code == 403
