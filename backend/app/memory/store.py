"""Mémoire : abstraction MemoryStore (conversation / projet / agent), implémentation SQL.
Un `Embedder` optionnel permettra d'ajouter la recherche vectorielle (RAG) sans changer les appelants."""
from __future__ import annotations
import re
import uuid
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import FileChunk, Memory

SCOPES = ("conversation", "project", "agent")


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def keywords(query: str, limit: int = 6) -> list[str]:
    words = {w.lower() for w in re.findall(r"\w{4,}", query)}
    return sorted(words, key=len, reverse=True)[:limit]


class DBMemoryStore:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID, embedder: Embedder | None = None):
        self.db, self.org_id, self.embedder = db, org_id, embedder

    async def add(self, scope: str, scope_id: str, content: str, meta: dict | None = None) -> Memory:
        if scope not in SCOPES:
            raise ValueError(f"scope doit être l'un de {SCOPES}")
        m = Memory(organization_id=self.org_id, scope=scope, scope_id=scope_id, content=content[:20000], meta=meta or {})
        if self.embedder:
            m.embedding = (await self.embedder.embed([content]))[0]
        self.db.add(m)
        await self.db.flush()
        return m

    async def recall(self, scope: str, scope_id: str, query: str = "", limit: int = 8) -> list[Memory]:
        q = select(Memory).where(Memory.organization_id == self.org_id, Memory.scope == scope,
                                 Memory.scope_id == scope_id, Memory.deleted_at.is_(None))
        kws = keywords(query)
        if kws:
            q = q.where(or_(*[Memory.content.ilike(f"%{k}%") for k in kws]))
        return list((await self.db.execute(q.order_by(Memory.created_at.desc()).limit(limit))).scalars())

    async def search_files(self, query: str, limit: int = 5) -> list[FileChunk]:
        kws = keywords(query)
        if not kws:
            return []
        q = select(FileChunk).where(FileChunk.organization_id == self.org_id,
                                    or_(*[FileChunk.content.ilike(f"%{k}%") for k in kws])).limit(limit)
        return list((await self.db.execute(q)).scalars())
