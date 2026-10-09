"""Mémoire : abstraction MemoryStore (conversation / projet / agent), implémentation SQL.
Un `Embedder` optionnel permettra d'ajouter la recherche vectorielle (RAG) sans changer les appelants."""
from __future__ import annotations
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import FileChunk, Memory

# Niveaux de mémoire (§23) : conversation, courte durée (TTL), projet, utilisateur, agent, organisation.
# La recherche sémantique s'applique à tous les niveaux dès qu'un Embedder est fourni ; l'historique des exécutions
# reste consultable via l'API des exécutions.
SCOPES = ("conversation", "short", "project", "user", "agent", "organization")
SHORT_TTL_S = 7200


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def keywords(query: str, limit: int = 6) -> list[str]:
    words = {w.lower() for w in re.findall(r"\w{4,}", query)}
    return sorted(words, key=len, reverse=True)[:limit]


def _expired(m: Memory) -> bool:
    exp = (m.meta or {}).get("expires_at")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(exp) < datetime.now(timezone.utc)
    except ValueError:
        return False


class DBMemoryStore:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID, embedder: Embedder | None = None):
        self.db, self.org_id, self.embedder = db, org_id, embedder

    async def add(self, scope: str, scope_id: str, content: str, meta: dict | None = None) -> Memory:
        if scope not in SCOPES:
            raise ValueError(f"scope doit être l'un de {SCOPES}")
        meta = dict(meta or {})
        if scope == "short":
            meta.setdefault("expires_at", (datetime.now(timezone.utc) + timedelta(seconds=SHORT_TTL_S)).isoformat())
        m = Memory(organization_id=self.org_id, scope=scope, scope_id=scope_id, content=content[:20000], meta=meta)
        if self.embedder:
            m.embedding = (await self.embedder.embed([content]))[0]
        self.db.add(m)
        await self.db.flush()
        return m

    async def recall(self, scope: str, scope_id: str, query: str = "", limit: int = 8) -> list[Memory]:
        q = select(Memory).where(Memory.organization_id == self.org_id, Memory.scope == scope,
                                 Memory.scope_id == scope_id, Memory.deleted_at.is_(None))
        if self.embedder and query.strip():  # recherche sémantique/hybride sur les 500 souvenirs les plus récents
            rows = list((await self.db.execute(q.order_by(Memory.created_at.desc()).limit(500))).scalars())
            rows = [r for r in rows if not _expired(r)]
            from app.rag.search import Doc, hybrid_search
            qvec = (await self.embedder.embed([query]))[0]
            docs = [Doc(r.id, r.content, r.embedding, {"row": r}) for r in rows]
            hits = hybrid_search(query, qvec, docs, k=limit)
            return [h.doc.meta["row"] for h in hits] or rows[:limit]
        kws = keywords(query)
        if kws:
            q = q.where(or_(*[Memory.content.ilike(f"%{k}%") for k in kws]))
        rows = list((await self.db.execute(q.order_by(Memory.created_at.desc()).limit(limit * 2))).scalars())
        return [r for r in rows if not _expired(r)][:limit]

    async def recall_many(self, targets: list[tuple[str, str]], query: str = "", limit: int = 8) -> list[Memory]:
        """Rappel combiné sur plusieurs niveaux (ex. [("user", uid), ("project", pid), ("organization", oid)])."""
        out: list[Memory] = []
        for scope, sid in targets:
            out += await self.recall(scope, sid, query, limit)
        return out[:limit * 2]

    async def search_files(self, query: str, limit: int = 5) -> list[FileChunk]:
        kws = keywords(query)
        if not kws:
            return []
        q = select(FileChunk).where(FileChunk.organization_id == self.org_id,
                                    or_(*[FileChunk.content.ilike(f"%{k}%") for k in kws])).limit(limit)
        return list((await self.db.execute(q)).scalars())
