import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .chat import run_chat
from .config import settings
from .db import Approval, Ticket, async_session, init_db
from .integrations import camunda_client, datahub_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dgo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(title="Intelligent Data Governance API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Shared-secret gate for every route on `api_router` below - see the
    comment on `settings.api_key` for what this does and doesn't cover.
    Empty `settings.api_key` (the default) disables this check entirely,
    same convention as this app's other optional integrations."""
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="missing or invalid API key")


# Every route below requires X-API-Key (when settings.api_key is set) -
# using a router rather than per-route dependencies so a route added here
# later is protected by default instead of by remembering to add it.
# /health stays on the bare `app` below, unauthenticated - status checks
# (docker healthchecks, load balancers) shouldn't need a secret.
api_router = APIRouter(dependencies=[Depends(require_api_key)])


@app.get("/health")
async def health():
    return {"status": "ok"}


@api_router.get("/api/catalog")
async def get_catalog():
    return await datahub_client.get_catalog()


@api_router.get("/api/catalog/{product_id}/connection")
async def get_connection_meta(product_id: str):
    catalog = await datahub_client.get_catalog()
    item = catalog.get(product_id)
    if not item:
        raise HTTPException(status_code=404, detail="unknown product_id")
    return {
        "db_type": item.get("db_type", ""),
        "db_host": item.get("db_host", ""),
        "db_port": item.get("db_port", ""),
        "db_schema": item.get("db_schema", ""),
    }


@api_router.post("/api/chat")
async def chat(request: Request):
    payload = await request.json()
    user_msg = payload.get("message", "").strip()
    lang = "en" if payload.get("lang") == "en" else "zh"
    logger.info("Chat request: %r (lang=%s)", user_msg, lang)
    catalog = await datahub_client.get_catalog()

    return StreamingResponse(
        run_chat(user_msg, lang, catalog),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _ticket_to_dict(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "products": ticket.products,
        "objective": ticket.objective,
        "purpose": ticket.purpose,
        "status": ticket.status,
        "owners": ticket.owners,
        "created_at": ticket.created_at.isoformat(),
        "approvals": {
            a.owner_email: {
                "decision": a.decision,
                "reason": a.reason,
                "created_at": a.created_at.isoformat(),
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                "cycle_time_seconds": a.cycle_time_seconds,
            }
            for a in ticket.approvals
        },
    }


@api_router.post("/api/tickets")
async def create_ticket(request: Request):
    payload = await request.json()
    products = payload["products"]
    objective = payload["objective"]
    purpose = payload["purpose"]

    catalog = await datahub_client.get_catalog()
    owners: list[str] = []
    for product_id in products:
        item = catalog.get(product_id)
        if item and item["owner"] not in owners:
            owners.append(item["owner"])
    if len(owners) < 3:
        owners.extend(settings.default_fallback_approvers_list)

    ticket_id = f"FAB-{uuid.uuid4().hex[:6].upper()}"
    async with async_session() as session:
        ticket = Ticket(
            id=ticket_id,
            products=products,
            objective=objective,
            purpose=purpose,
            status="PENDING_APPROVAL",
            owners=owners,
        )
        session.add(ticket)
        for owner in owners:
            session.add(Approval(ticket_id=ticket_id, owner_email=owner, decision="PENDING"))
        await session.commit()
        logger.info("Ticket %s created, owners=%s", ticket_id, owners)

    camunda_result = await camunda_client.start_approval_process(ticket_id, products, owners, purpose)
    logger.info("Ticket %s Camunda status: %s", ticket_id, camunda_result.status)

    if camunda_result.process_instance_id:
        async with async_session() as session:
            saved_ticket = await session.get(Ticket, ticket_id)
            if saved_ticket:
                saved_ticket.camunda_process_instance_id = camunda_result.process_instance_id
                await session.commit()

    return {"ticket_id": ticket_id, "camunda_status": camunda_result.status}


@api_router.get("/api/tickets")
async def list_tickets():
    async with async_session() as session:
        result = await session.execute(
            select(Ticket).options(selectinload(Ticket.approvals)).order_by(Ticket.created_at.desc())
        )
        tickets = result.scalars().unique().all()
        return [_ticket_to_dict(t) for t in tickets]


@api_router.post("/api/tickets/{ticket_id}/approvals")
async def submit_approval(ticket_id: str, request: Request):
    payload = await request.json()
    owner_email = payload["owner_email"]
    decision = payload["decision"]
    reason = payload.get("reason", "")
    logger.info("Approval: ticket=%s owner=%s decision=%s", ticket_id, owner_email, decision)

    async with async_session() as session:
        result = await session.execute(
            select(Ticket).options(selectinload(Ticket.approvals)).where(Ticket.id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=404, detail="ticket not found")

        approval = next((a for a in ticket.approvals if a.owner_email == owner_email), None)
        if not approval:
            raise HTTPException(status_code=404, detail="approver not found on this ticket")

        now = datetime.now(UTC)
        approval.decision = decision
        approval.reason = reason
        approval.completed_at = now
        # created_at always stored as UTC (see db.py's default), but not
        # every DB backend round-trips the tzinfo on read (SQLite doesn't;
        # Postgres does) - normalize rather than assume, or the subtraction
        # below raises TypeError on a naive/aware mismatch.
        created_at = approval.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        approval.cycle_time_seconds = (now - created_at).total_seconds()

        states = [a.decision for a in ticket.approvals]
        if "Reject" in states:
            ticket.status = "REJECTED"
        elif all(s != "PENDING" for s in states):
            ticket.status = "APPROVED"

        await session.commit()
        logger.info("Ticket %s new status=%s", ticket_id, ticket.status)
        process_instance_id = ticket.camunda_process_instance_id

    camunda_status = await camunda_client.complete_approval_task(
        process_instance_id, owner_email, decision, reason
    )
    logger.info("Ticket %s Camunda task completion: %s", ticket_id, camunda_status)

    return {"status": "success"}


app.include_router(api_router)
