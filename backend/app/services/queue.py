import redis.asyncio as redis
from app.core.config import get_settings

QUEUE = "aiw:executions"


def client() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def enqueue(execution_id: str) -> None:
    r = client()
    try:
        await r.rpush(QUEUE, execution_id)
    finally:
        await r.aclose()
