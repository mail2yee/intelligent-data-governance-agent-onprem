"""
Test database is SQLite (file-based, not :memory: - SQLAlchemy's async
engine pools connections, and :memory: gives each new connection a fresh
empty DB unless you special-case StaticPool; a temp file avoids that
footgun entirely). This is a deliberate tradeoff for speed/simplicity
over testing against real Postgres - fine for exercising application
logic (the ticket state machine, API contracts, chat streaming), since
nothing here relies on Postgres-specific SQL. Revisit with a real-Postgres
integration tier if that ever changes.

DATABASE_URL must be set before `app.db` (and anything importing it) is
imported, since the engine is created at module import time.
"""

import os
import tempfile

_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_db_fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp_db_path}"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
