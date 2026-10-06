from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import Agent, AuditLog, Execution, Project, Task, UsageRecord
from app.services.quota import month_start, storage_bytes, subscription, tokens_this_month
from .common import ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage")
async def usage(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    org, since = c.org_id, month_start()
    sub = await subscription(db, org)
    calls, exec_ms = (await db.execute(select(func.coalesce(func.sum(UsageRecord.llm_calls), 0),
                      func.coalesce(func.sum(UsageRecord.duration_ms), 0)).where(
                      UsageRecord.organization_id == org, UsageRecord.created_at >= since))).one()
    count = lambda m, *w: select(func.count()).select_from(m).where(m.organization_id == org, *w)
    executions = (await db.execute(count(Execution, Execution.created_at >= since))).scalar_one()
    projects = (await db.execute(count(Project, Project.deleted_at.is_(None)))).scalar_one()
    agents = (await db.execute(count(Agent, Agent.deleted_at.is_(None)))).scalar_one()
    by_agent = (await db.execute(select(UsageRecord.agent, func.sum(UsageRecord.tokens)).where(
        UsageRecord.organization_id == org, UsageRecord.created_at >= since).group_by(UsageRecord.agent))).all()
    day = func.date(UsageRecord.created_at)
    daily = (await db.execute(select(day, func.sum(UsageRecord.tokens)).where(
        UsageRecord.organization_id == org, UsageRecord.created_at >= datetime.now(timezone.utc) - timedelta(days=14))
        .group_by(day).order_by(day))).all()
    return ok({"tokens": await tokens_this_month(db, org), "token_limit": sub.monthly_token_limit,
               "llm_calls": calls, "execution_time_ms": exec_ms, "executions": executions, "projects": projects,
               "agents": agents, "storage_bytes": await storage_bytes(db, org), "storage_limit_mb": sub.storage_limit_mb,
               "plan": sub.plan, "by_agent": [{"agent": a or "chat", "tokens": int(t or 0)} for a, t in by_agent],
               "daily": [{"day": str(d), "tokens": int(t or 0)} for d, t in daily]})


@router.get("/dashboard")
async def dashboard(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    org = c.org_id
    running = (await db.execute(select(func.count()).select_from(Task).where(
        Task.organization_id == org, Task.status == "RUNNING"))).scalar_one()
    active = (await db.execute(select(func.count()).select_from(Execution).where(
        Execution.organization_id == org, Execution.status.in_(["PENDING", "RUNNING", "CANCELLING"])))).scalar_one()
    recent = (await db.execute(select(Execution).where(Execution.organization_id == org)
              .order_by(Execution.created_at.desc()).limit(8))).scalars().all()
    errors = (await db.execute(select(Execution).where(Execution.organization_id == org, Execution.status == "FAILED")
              .order_by(Execution.created_at.desc()).limit(5))).scalars().all()
    agents = (await db.execute(select(Task.agent, Task.status).where(Task.organization_id == org,
              Task.status.in_(["RUNNING", "PENDING", "QUEUED", "WAITING"])).limit(50))).all()
    return ok({"running_tasks": running, "active_executions": active,
               "recent": [{"id": str(e.id), "mission": e.mission[:140], "status": e.status, "tokens": e.tokens,
                           "created_at": e.created_at.isoformat()} for e in recent],
               "errors": [{"id": str(e.id), "mission": e.mission[:100], "error": (e.error or "")[:200]} for e in errors],
               "agent_monitor": [{"agent": a, "status": s} for a, s in agents]})
