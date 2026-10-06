"""Organisations, mémoire, messages, tâches, notifications, clés API."""
import secrets
import uuid
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import hash_api_key
from app.memory.store import SCOPES, DBMemoryStore
from app.models.entities import (AgentMessage, ApiKey, Execution, Memory, Notification, Organization,
                                 OrganizationMember, Role, Subscription, Task, TaskDependency, User)
from app.services.audit import audit
from .common import ok, owned
from .deps import Ctx, ctx, current_user

router = APIRouter(prefix="/api", tags=["misc"])


# ----- organisations
class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/organizations")
async def list_orgs(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(OrganizationMember, Organization).join(Organization)
            .where(OrganizationMember.user_id == user.id, Organization.deleted_at.is_(None)))).all()
    return ok([{"id": str(o.id), "name": o.name, "role": m.role.value} for m, o in rows])


@router.post("/organizations", status_code=201)
async def create_org(b: OrgIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    o = Organization(name=b.name); db.add(o); await db.flush()
    db.add_all([OrganizationMember(organization_id=o.id, user_id=user.id, role=Role.OWNER), Subscription(organization_id=o.id)])
    await audit(db, "org.create", user_id=user.id, org_id=o.id, resource="organization", resource_id=o.id, request=request)
    await db.commit()
    return ok({"id": str(o.id), "name": o.name})


# ----- mémoire
class MemoryIn(BaseModel):
    scope: str
    scope_id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=20000)


@router.get("/memory")
async def get_memory(scope: str, scope_id: str, q: str = "", c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    if scope not in SCOPES:
        raise AppError(422, "VALIDATION_ERROR", f"scope doit être l'un de: {', '.join(SCOPES)}")
    rows = await DBMemoryStore(db, c.org_id).recall(scope, scope_id, q, limit=50)
    return ok([{"id": str(m.id), "scope": m.scope, "scope_id": m.scope_id, "content": m.content,
                "created_at": m.created_at.isoformat()} for m in rows])


@router.post("/memory", status_code=201)
async def add_memory(b: MemoryIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    if b.scope not in SCOPES:
        raise AppError(422, "VALIDATION_ERROR", f"scope doit être l'un de: {', '.join(SCOPES)}")
    m = await DBMemoryStore(db, c.org_id).add(b.scope, b.scope_id, b.content, {"by": str(c.user.id)})
    await db.commit()
    return ok({"id": str(m.id)})


@router.delete("/memory/{mem_id}", status_code=204)
async def delete_memory(mem_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    (await owned(db, Memory, mem_id, c.org_id, "Mémoire")).deleted_at = func.now()
    await db.commit()


# ----- messages entre agents, tâches
@router.get("/messages")
async def messages(execution_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    await owned(db, Execution, execution_id, c.org_id, "Exécution")
    rows = (await db.execute(select(AgentMessage).where(AgentMessage.organization_id == c.org_id,
            AgentMessage.execution_id == execution_id).order_by(AgentMessage.id).limit(500))).scalars()
    return ok([{"id": m.id, "sender": m.sender, "recipient": m.recipient, "content": m.content,
                "created_at": m.created_at.isoformat()} for m in rows])


@router.get("/tasks")
async def tasks(execution_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    await owned(db, Execution, execution_id, c.org_id, "Exécution")
    ts = (await db.execute(select(Task).where(Task.organization_id == c.org_id, Task.execution_id == execution_id))).scalars().all()
    deps = (await db.execute(select(TaskDependency).where(TaskDependency.task_id.in_([t.id for t in ts] or [None])))).scalars().all()
    by = {}
    for d in deps:
        by.setdefault(d.task_id, []).append(str(d.depends_on_id))
    return ok([{"id": str(t.id), "key": t.key, "title": t.title, "agent": t.agent, "status": t.status,
                "tokens": t.tokens, "duration_ms": t.duration_ms, "error": t.error, "output": t.output,
                "depends_on": by.get(t.id, [])} for t in ts])


# ----- notifications
@router.get("/notifications")
async def notifications(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Notification).where(Notification.user_id == c.user.id,
            Notification.organization_id == c.org_id).order_by(Notification.id.desc()).limit(50))).scalars()
    return ok([{"id": n.id, "title": n.title, "body": n.body, "read": n.read, "created_at": n.created_at.isoformat()} for n in rows])


@router.post("/notifications/{nid}/read", status_code=204)
async def read_notification(nid: int, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.id == nid, Notification.user_id == c.user.id).values(read=True))
    await db.commit()


# ----- clés API
class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get("/api-keys")
async def list_keys(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ApiKey).where(ApiKey.organization_id == c.org_id, ApiKey.user_id == c.user.id,
                                                  ApiKey.deleted_at.is_(None)))).scalars()
    return ok([{"id": str(k.id), "name": k.name, "prefix": k.prefix, "created_at": k.created_at.isoformat()} for k in rows])


@router.post("/api-keys", status_code=201)
async def create_key(b: KeyIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    raw = "aiw_" + secrets.token_urlsafe(32)
    k = ApiKey(organization_id=c.org_id, user_id=c.user.id, name=b.name, prefix=raw[:10], key_hash=hash_api_key(raw))
    db.add(k)
    await audit(db, "apikey.create", user_id=c.user.id, org_id=c.org_id, resource="api_key", request=request)
    await db.commit()
    return ok({"id": str(k.id), "key": raw, "notice": "Cette clé ne sera plus affichée."})


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_key(key_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    k = await owned(db, ApiKey, key_id, c.org_id, "Clé API")
    if k.user_id != c.user.id:
        c.require(Role.ADMIN)
    k.deleted_at = func.now(); await db.commit()
