from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from .config import get_settings

_engine = None
_maker = None


def session_maker() -> async_sessionmaker[AsyncSession]:
    global _engine, _maker
    if _maker is None:
        url = get_settings().database_url
        kw = {} if url.startswith("sqlite") else {"pool_size": 10, "pool_pre_ping": True}
        _engine = create_async_engine(url, **kw)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _maker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_maker()() as s:
        yield s
