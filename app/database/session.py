import os
from collections.abc import AsyncGenerator
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import settings
from app.database.models import Achievement, Base, DEFAULT_ACHIEVEMENTS

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

def ensure_db_dir(db_url: str) -> None:
    if "sqlite" in db_url and "///" in db_url:
        path = db_url.split("///", 1)[1].split("?", 1)[0]
        if path and path != ":memory:" and not path.startswith(":memory:"):
            dir_name = os.path.dirname(path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

async def init_db(target_engine=None) -> None:
    current_engine = target_engine if target_engine is not None else engine
    ensure_db_dir(str(current_engine.url))
    async with current_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(
        bind=current_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        result = await session.execute(select(Achievement.code))
        existing_codes = set(result.scalars().all())
        to_add = [
            Achievement(**item)
            for item in DEFAULT_ACHIEVEMENTS
            if item["code"] not in existing_codes
        ]
        if to_add:
            session.add_all(to_add)
            await session.commit()
