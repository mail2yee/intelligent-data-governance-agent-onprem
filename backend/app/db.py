from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import settings


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    # String(N) everywhere below, not bare String - MariaDB/MySQL's
    # VARCHAR requires an explicit length (Postgres's doesn't), so a bare
    # String compiles to invalid DDL on this dialect. Free-form text
    # fields use Text instead, which needs no length on either dialect.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    products: Mapped[list] = mapped_column(JSON)
    objective: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_APPROVAL")
    owners: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Set from integrations.camunda_client.start_approval_process()'s
    # result once a Camunda process instance actually starts (None if
    # Camunda was unreachable, or no process instance exists for this
    # ticket) - needed later to find and complete the right owner's task
    # in camunda_client.complete_approval_task() (see main.py's
    # submit_approval).
    camunda_process_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    approvals: Mapped[list["Approval"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(String(64), ForeignKey("tickets.id"))
    owner_email: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(32), default="PENDING")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="approvals")


class DataProduct(Base):
    """Mirror of the DataHub catalog, kept in our own database so WrenAI's
    governed engine has a real table to validate/execute agent-written SQL
    against (see integrations/wrenai_client.py) - WrenAI needs a live
    connected data source, it can't validate against a Python dict.
    Repopulated from datahub_client.get_catalog() on each chat request
    (see chat.py), not treated as its own source of truth.
    """

    __tablename__ = "data_products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(255))
    maturity_level: Mapped[str] = mapped_column(String(64))
    data_quality_score: Mapped[str] = mapped_column(String(64))
    frequency: Mapped[str] = mapped_column(String(64))
    tables_joined: Mapped[str] = mapped_column(Text)
    db_type: Mapped[str] = mapped_column(String(64))
    db_host: Mapped[str] = mapped_column(String(255))
    db_port: Mapped[str] = mapped_column(String(16))
    db_schema: Mapped[str] = mapped_column(String(255))
    # Denormalized name+description+tables_joined, stored in both
    # Traditional and Simplified Chinese (see wrenai_client._search_text) -
    # the LLM's SQL-generation step matches keywords against this single
    # column instead of name/description/tables_joined individually, so a
    # keyword in either script still hits (confirmed: small local LLMs
    # sometimes emit Simplified keywords for a Traditional-Chinese catalog,
    # and plain ILIKE does no script folding).
    search_text: Mapped[str] = mapped_column(Text)


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
    message: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Set by scripts/review_unmatched_queries.py once a row has been
    # surfaced to a human for review - not "confirmed useful", just
    # "already shown", so re-running the script doesn't resurface the
    # same rows every time.
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)


class UserIdentity(Base):
    """Trust-on-first-use binding between a self-declared `user_key`
    (a name/email, typed into the frontend's profile dialog) and a
    random token minted client-side and stored in that browser's
    localStorage (see identity.py's module docstring for the full
    rationale and threat model this does/doesn't cover).

    Added 2026-09-05 in response to a security review that found
    `user_key` had NO ownership check at all - anyone could read/wipe
    another person's preferences, or (via the same self-declared field
    on ticket approvals) submit an approval decision as any owner just
    by knowing their email, since `submit_approval()` never verified
    the caller actually was that owner. This does not add real identity
    (there is still no SSO/OIDC - see main.py's submit_approval
    docstring) - it adds the ability to *distinguish* individuals from
    each other: whoever registered a `user_key` first is the only one
    who can act as it again, closing the "just guess/read someone's
    email and act as them" class of attack, at the cost of still being
    fully self-declared (a determined insider who obtains someone's
    token, or who claims a name nobody's claimed yet, isn't stopped).
    Real per-user auth requires the company's SSO/OIDC, deferred until
    that's available.
    """

    __tablename__ = "user_identities"

    user_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class UserPreference(Base):
    """Preferences extracted from a user's own past chat turns (see
    preferences.py) - keyed by the same `user_key` as `UserIdentity`
    above, which is what now actually gates read/write access to this
    table (see the /api/preferences endpoints) - this model itself
    stores content, not identity.
    """

    __tablename__ = "user_preferences"

    user_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Short strings, capped at preferences.MAX_PREFERENCES - oldest/least
    # useful dropped by the LLM itself when asked to fold in a new one
    # past the cap (see preferences.py's prompt), not truncated here.
    preferences: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
