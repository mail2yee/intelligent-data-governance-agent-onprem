from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
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


engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
