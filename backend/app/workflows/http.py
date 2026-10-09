"""Appels HTTP sortants des workflows, protégés contre le SSRF (HTTPS public uniquement, pas de redirection)."""
from __future__ import annotations
import asyncio

from app.services.urlcheck import validate_provider_url

MAX_BODY = 100_000


async def safe_http(method: str, url: str, headers: dict | None = None, body: str | None = None,
                    *, allow_private: bool = False, timeout: float = 20.0) -> tuple[int, str]:
    checked = await asyncio.to_thread(validate_provider_url, url, allow_private=allow_private)
    import httpx
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
        r = await c.request(method, checked, headers=headers or {}, content=body.encode() if body else None)
    return r.status_code, r.text[:MAX_BODY]
