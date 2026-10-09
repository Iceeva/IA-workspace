"""Sécurité d'une organisation (§21, §22, §33) : journal d'audit filtré et synthèse des expositions."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import (ApiKey, ApprovalRequest, AuditLog, CustomAgent, ProviderConfig, Role, WorkflowTrigger)
from .common import ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api/security", tags=["security"])
DANGEROUS = ("EXECUTE", "WRITE")


def risky_tools(definition: dict) -> dict[str, str]:
    """Outils d'un agent accordés au-dessus de la lecture (WRITE/EXECUTE) : ce qu'un administrateur doit relire."""
    return {t: lvl for t, lvl in (definition.get("tools") or {}).items() if str(lvl).upper() in DANGEROUS}


@router.get("/audit")
async def audit_log(action: str | None = Query(None, max_length=60), limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0), c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    q = select(AuditLog).where(AuditLog.organization_id == c.org_id)
    if action:
        q = q.where(AuditLog.action.like(action.replace("%", "") + "%"))
    rows = (await db.execute(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset))).scalars()
    return ok([{"id": a.id, "action": a.action, "user_id": str(a.user_id) if a.user_id else None, "resource": a.resource,
                "resource_id": a.resource_id, "ip": a.ip, "meta": a.meta, "created_at": a.created_at.isoformat()} for a in rows])


@router.get("/overview")
async def overview(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    org, day = c.org_id, datetime.now(timezone.utc) - timedelta(days=1)
    providers = (await db.execute(select(ProviderConfig).where(ProviderConfig.organization_id == org))).scalars().all()
    custom = (await db.execute(select(CustomAgent).where(CustomAgent.organization_id == org, CustomAgent.deleted_at.is_(None)))).scalars().all()
    keys = (await db.execute(select(func.count()).select_from(ApiKey).where(ApiKey.organization_id == org, ApiKey.deleted_at.is_(None)))).scalar_one()
    hooks = (await db.execute(select(func.count()).select_from(WorkflowTrigger).where(
        WorkflowTrigger.organization_id == org, WorkflowTrigger.type.in_(["webhook", "github"]),
        WorkflowTrigger.enabled.is_(True), WorkflowTrigger.deleted_at.is_(None)))).scalar_one()
    appr = dict((await db.execute(select(ApprovalRequest.status, func.count()).where(
        ApprovalRequest.organization_id == org, ApprovalRequest.created_at >= day).group_by(ApprovalRequest.status))).all())
    return ok({
        "providers": {"total": len(providers), "with_key": sum(bool(p.api_key_enc) for p in providers),
                      "local": sum(bool(p.local) or p.kind == "bridge" for p in providers),
                      "cloud_without_key": [p.name for p in providers if not p.api_key_enc and not p.local and p.kind not in ("bridge", "ollama", "lmstudio", "llamacpp", "localai", "vllm")]},
        "custom_agents_with_risky_tools": [{"id": a.agent_id, "tools": risky_tools(a.definition)} for a in custom if risky_tools(a.definition)],
        "api_keys": keys, "public_webhooks": hooks,
        "approvals_24h": {"approved": appr.get("APPROVED", 0), "denied": appr.get("DENIED", 0), "pending": appr.get("PENDING", 0),
                          "expired": appr.get("EXPIRED", 0)}})
