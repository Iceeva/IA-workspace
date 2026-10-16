"""Registre des runtimes persistant (§19) : le navigateur y dépose ce que son Local Bridge détecte ; le serveur le conserve."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import RANK, Role, RuntimeRecord
from app.runtimes.report import ReportError, is_stale, sanitize_report
from .common import AppError, ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


def _dto(r: RuntimeRecord, now: datetime) -> dict:
    age = (now - r.last_seen).total_seconds() if r.last_seen else 1e9
    return {"id": str(r.id), "runtime_id": r.runtime_id, "kind": r.kind, "name": r.name, "base_url": r.base_url, "status": r.status,
            "version": r.version, "capabilities": r.capabilities, "models": r.models, "latency_ms": r.latency_ms,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None, "stale": is_stale(age), "mine": None}


async def persist_runtimes(db: AsyncSession, org_id, user_id, items: list[dict]) -> None:
    """Remplace l'état connu des runtimes d'un utilisateur (navigateur ou poll du bridge) par `items`, déjà assainis."""
    now = datetime.now(timezone.utc)
    have = {r.runtime_id: r for r in (await db.execute(select(RuntimeRecord).where(
        RuntimeRecord.organization_id == org_id, RuntimeRecord.user_id == user_id))).scalars()}
    for it in items:
        row = have.pop(it["runtime_id"], None) or RuntimeRecord(organization_id=org_id, user_id=user_id, runtime_id=it["runtime_id"])
        for k, v in it.items():
            setattr(row, k, v)
        row.last_seen = now
        db.add(row)
    for gone in have.values():                      # absent du dernier rapport : marqué injoignable (on garde l'historique)
        gone.status = "unreachable"
    await db.commit()


@router.post("/report")
async def report(body: dict = Body(...), c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Remplace l'état connu des runtimes de CET utilisateur par celui que son bridge vient de détecter."""
    c.require(Role.MEMBER)
    try:
        items = sanitize_report(body)
    except ReportError as e:
        raise AppError(422, "BAD_REPORT", str(e))
    await persist_runtimes(db, c.org_id, c.user.id, items)
    return ok({"stored": len(items)})


@router.get("")
async def list_runtimes(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Runtimes connus de l'organisation (chacun ne voit que ses propres machines sauf administrateur)."""
    q = select(RuntimeRecord).where(RuntimeRecord.organization_id == c.org_id)
    if RANK[c.role] < RANK[Role.ADMIN]:
        q = q.where(RuntimeRecord.user_id == c.user.id)
    now = datetime.now(timezone.utc)
    rows = (await db.execute(q.order_by(RuntimeRecord.last_seen.desc()))).scalars().all()
    return ok([{**_dto(r, now), "mine": r.user_id == c.user.id} for r in rows])


@router.delete("/{rid}")
async def forget(rid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    q = delete(RuntimeRecord).where(RuntimeRecord.id == rid, RuntimeRecord.organization_id == c.org_id)
    if RANK[c.role] < RANK[Role.ADMIN]:
        q = q.where(RuntimeRecord.user_id == c.user.id)
    res = await db.execute(q)
    await db.commit()
    if not res.rowcount:
        raise AppError(404, "NOT_FOUND", "Runtime introuvable")
    return ok({"deleted": True})
