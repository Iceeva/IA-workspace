import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
from app.models.entities import Base

target = Base.metadata


def _run(conn):
    context.configure(connection=conn, target_metadata=target, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _main():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as c:
        await c.run_sync(_run)
    await engine.dispose()


asyncio.run(_main())
