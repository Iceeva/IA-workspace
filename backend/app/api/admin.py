"""Administration de la plateforme (réservée à is_platform_admin)."""
import uuid
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppError
from app.models.entities import (Agent, AuditLog, Execution, LLMModelConfig, LLMProviderConfig, Organization,
                                 Subscription, UsageRecord, User, Workspace)
from app.services.audit import audit
from .common import ok
from .deps import platform_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])
PROVIDERS = ("openrouter", "openai", "anthropic", "ollama")


def page(limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    return limit, offset


@router.get("/users")
async def users(p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).order_by(User.created_at.desc()).limit(p[0]).offset(p[1]))).scalars()
    return ok([{"id": str(u.id), "email": u.email, "full_name": u.full_name, "verified": u.email_verified,
                "disabled": u.deleted_at is not None, "is_platform_admin": u.is_platform_admin} for u in rows])


@router.post("/users/{uid}/disable", status_code=204)
async def disable_user(uid: uuid.UUID, request: Request, admin: User = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Utilisateur introuvable")
    if u.id == admin.id:
        raise AppError(409, "FORBIDDEN_SELF", "Vous ne pouvez pas désactiver votre propre compte")
    u.deleted_at = func.now()
    await audit(db, "admin.user_disable", user_id=admin.id, resource="user", resource_id=u.id, request=request)
    await db.commit()


@router.get("/organizations")
async def orgs(p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Organization, Subscription).outerjoin(
        Subscription, Subscription.organization_id == Organization.id).order_by(Organization.created_at.desc())
        .limit(p[0]).offset(p[1]))).all()
    return ok([{"id": str(o.id), "name": o.name, "plan": s.plan if s else "free",
                "monthly_token_limit": s.monthly_token_limit if s else None,
                "storage_limit_mb": s.storage_limit_mb if s else None} for o, s in rows])


class LimitsIn(BaseModel):
    plan: str = Field(max_length=30)
    monthly_token_limit: int = Field(ge=0)
    storage_limit_mb: int = Field(ge=0)


@router.put("/organizations/{org_id}/limits")
async def set_limits(org_id: uuid.UUID, b: LimitsIn, request: Request, admin: User = Depends(platform_admin),
                     db: AsyncSession = Depends(get_db)):
    from app.services.quota import subscription
    sub = await subscription(db, org_id)
    sub.plan, sub.monthly_token_limit, sub.storage_limit_mb = b.plan, b.monthly_token_limit, b.storage_limit_mb
    await audit(db, "admin.limits", user_id=admin.id, org_id=org_id, resource="subscription", request=request, meta=b.model_dump())
    await db.commit()
    return ok({"org_id": str(org_id)})


@router.get("/workspaces")
async def workspaces(p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workspace).where(Workspace.deleted_at.is_(None)).limit(p[0]).offset(p[1]))).scalars()
    return ok([{"id": str(w.id), "name": w.name, "organization_id": str(w.organization_id)} for w in rows])


@router.get("/agents")
async def agents(p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Agent).where(Agent.deleted_at.is_(None)).limit(p[0]).offset(p[1]))).scalars()
    return ok([{"id": str(a.id), "name": a.name, "role": a.role, "model": a.model,
                "organization_id": str(a.organization_id)} for a in rows])


@router.get("/executions")
async def executions(status: str | None = None, p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    q = select(Execution).order_by(Execution.created_at.desc()).limit(p[0]).offset(p[1])
    if status:
        q = q.where(Execution.status == status)
    return ok([{"id": str(e.id), "organization_id": str(e.organization_id), "status": e.status, "tokens": e.tokens,
                "error": e.error, "mission": e.mission[:120]} for e in (await db.execute(q)).scalars()])


@router.get("/usage")
async def usage(_=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(UsageRecord.organization_id, func.sum(UsageRecord.tokens),
            func.sum(UsageRecord.llm_calls)).group_by(UsageRecord.organization_id)
            .order_by(func.sum(UsageRecord.tokens).desc()).limit(100))).all()
    return ok([{"organization_id": str(o), "tokens": int(t or 0), "llm_calls": int(c or 0)} for o, t, c in rows])


@router.get("/audit")
async def audit_log(p=Depends(page), _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(p[0]).offset(p[1]))).scalars()
    return ok([{"id": a.id, "action": a.action, "user_id": str(a.user_id) if a.user_id else None,
                "organization_id": str(a.organization_id) if a.organization_id else None, "resource": a.resource,
                "resource_id": a.resource_id, "ip": a.ip, "created_at": a.created_at.isoformat()} for a in rows])


class ProviderIn(BaseModel):
    enabled: bool


@router.get("/providers")
async def providers(_=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = {r.name: r.enabled for r in (await db.execute(select(LLMProviderConfig))).scalars()}
    return ok([{"name": n, "enabled": rows.get(n, True)} for n in PROVIDERS])


@router.put("/providers/{name}")
async def set_provider(name: str, b: ProviderIn, request: Request, admin: User = Depends(platform_admin),
                       db: AsyncSession = Depends(get_db)):
    if name not in PROVIDERS:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Provider inconnu")
    row = await db.get(LLMProviderConfig, name) or LLMProviderConfig(name=name)
    row.enabled = b.enabled; db.add(row)
    await audit(db, "admin.provider", user_id=admin.id, resource="provider", resource_id=name, request=request, meta={"enabled": b.enabled})
    await db.commit()
    return ok({"name": name, "enabled": b.enabled})


class ModelIn(BaseModel):
    provider: str
    model_id: str = Field(min_length=1, max_length=120)
    enabled: bool = True


@router.get("/models")
async def models(_=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    return ok([{"id": m.id, "provider": m.provider, "model_id": m.model_id, "enabled": m.enabled}
               for m in (await db.execute(select(LLMModelConfig))).scalars()])


@router.post("/models", status_code=201)
async def add_model(b: ModelIn, _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    if b.provider not in PROVIDERS:
        raise AppError(422, "VALIDATION_ERROR", "Provider inconnu")
    if not await db.get(LLMProviderConfig, b.provider):
        db.add(LLMProviderConfig(name=b.provider)); await db.flush()
    m = LLMModelConfig(provider=b.provider, model_id=b.model_id, enabled=b.enabled)
    db.add(m); await db.commit()
    return ok({"id": m.id})


@router.put("/models/{mid}")
async def toggle_model(mid: int, b: ProviderIn, _=Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    m = await db.get(LLMModelConfig, mid)
    if not m:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Modèle introuvable")
    m.enabled = b.enabled; await db.commit()
    return ok({"id": mid, "enabled": b.enabled})
