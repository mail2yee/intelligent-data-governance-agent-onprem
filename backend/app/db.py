from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import settings


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    products: Mapped[list] = mapped_column(JSON)
    objective: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PENDING_APPROVAL")
    owners: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Set from integrations.camunda_client.start_approval_process()'s
    # result once a Camunda process instance actually starts (None if
    # Camunda was unreachable, or no process instance exists for this
    # ticket) - needed later to find and complete the right owner's task
    # in camunda_client.complete_approval_task() (see main.py's
    # submit_approval).
    camunda_process_instance_id: Mapped[str | None] = mapped_column(String, nullable=True)

    approvals: Mapped[list["Approval"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    owner_email: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String, default="PENDING")
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="approvals")


class DataProduct(Base):
    """Mirror of the DataHub catalog, kept in our own Postgres so WrenAI's
    governed engine has a real table to validate/execute agent-written SQL
    against (see integrations/wrenai_client.py) - WrenAI needs a live
    connected data source, it can't validate against a Python dict.
    Repopulated from datahub_client.get_catalog() on each chat request
    (see chat.py), not treated as its own source of truth.
    """

    __tablename__ = "data_products"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String)
    maturity_level: Mapped[str] = mapped_column(String)
    data_quality_score: Mapped[str] = mapped_column(String)
    frequency: Mapped[str] = mapped_column(String)
    tables_joined: Mapped[str] = mapped_column(String)
    db_type: Mapped[str] = mapped_column(String)
    db_host: Mapped[str] = mapped_column(String)
    db_port: Mapped[str] = mapped_column(String)
    db_schema: Mapped[str] = mapped_column(String)
    # Denormalized name+description+tables_joined, stored in both
    # Traditional and Simplified Chinese (see wrenai_client._search_text) -
    # the LLM's SQL-generation step matches keywords against this single
    # column instead of name/description/tables_joined individually, so a
    # keyword in either script still hits (confirmed: small local LLMs
    # sometimes emit Simplified keywords for a Traditional-Chinese catalog,
    # and plain ILIKE does no script folding).
    search_text: Mapped[str] = mapped_column(String)


class UnmatchedQuery(Base):
    """Chat messages that reached chat.py's full AI-search pipeline (not
    caught by is_greeting()'s cheap keyword check) and ended up matching
    zero catalog entries - logged for periodic offline review (see
    scripts/review_unmatched_queries.py), not read by anything in the
    live request path itself.

    Why this exists: a live, per-request LLM classification of "is this
    actually a greeting/chit-chat" was tried and reverted 2026-07-31 (a
    small local model proved unreliable at that 3-way decision, see
    chat.py's build_prompt() comment) - logging these instead and
    reviewing them offline with an LLM as a human's triage assistant
    (not an unsupervised decision-maker) sidesteps that reliability
    problem entirely, since a human confirms any new keyword before it's
    added to is_greeting()'s CHITCHAT_WORDS/GREETING_WORDS.
    """

    __tablename__ = "unmatched_queries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message: Mapped[str] = mapped_column(String)
    lang: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Set by scripts/review_unmatched_queries.py once a row has been
    # surfaced to a human for review - not "confirmed useful", just
    # "already shown", so re-running the script doesn't resurface the
    # same rows every time.
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)


engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
