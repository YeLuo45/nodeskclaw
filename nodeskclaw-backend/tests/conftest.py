"""Shared test fixtures."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.deps import get_db
from app.main import app
from app.models import Base

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw@localhost:5432/nodeskclaw_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _drop_all_tables(sync_connection):
    preparer = sync_connection.dialect.identifier_preparer
    for table in Base.metadata.tables.values():
        sync_connection.execute(text(f"DROP TABLE IF EXISTS {preparer.format_table(table)} CASCADE"))


async def recreate_test_database(db_engine=engine) -> bool:
    try:
        async with db_engine.begin() as conn:
            await conn.run_sync(_drop_all_tables)
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await db_engine.dispose()
        return False
    return True


async def drop_test_database(db_engine=engine) -> None:
    try:
        async with db_engine.begin() as conn:
            await conn.run_sync(_drop_all_tables)
    except Exception:
        await db_engine.dispose()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    if not await recreate_test_database():
        yield
        app.dependency_overrides[get_db] = override_get_db
        return

    yield

    app.dependency_overrides[get_db] = override_get_db
    await drop_test_database()


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
