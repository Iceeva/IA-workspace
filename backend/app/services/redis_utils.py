"""Limiteur de débit et liste de révocation, partagés entre instances via Redis."""
import logging
from app.services.queue import client

log = logging.getLogger("redis")


async def rate_limited(key: str, limit: int, window_s: int = 60) -> bool:
    r = client()
    try:
        n = await r.incr(f"rl:{key}")
        if n == 1:
            await r.expire(f"rl:{key}", window_s)
        return n > limit
    except Exception:  # noqa: BLE001 — Redis indisponible : on laisse passer mais on le signale
        log.warning("rate limiter indisponible (redis)")
        return False
    finally:
        await r.aclose()


async def revoke(jti: str, ttl_s: int) -> None:
    r = client()
    try:
        await r.set(f"revoked:{jti}", "1", ex=max(ttl_s, 1))
    finally:
        await r.aclose()


async def is_revoked(jti: str) -> bool:
    r = client()
    try:
        return bool(await r.exists(f"revoked:{jti}"))
    except Exception:  # noqa: BLE001
        log.warning("liste de révocation indisponible (redis)")
        return False
    finally:
        await r.aclose()
