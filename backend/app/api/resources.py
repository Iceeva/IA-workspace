"""Workspaces, projets, agents, exécutions — toutes les requêtes filtrent sur ctx.org_id."""
import json
import uuid
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.roles import ROLES
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models.entities import Agent, Execution, ExecutionEvent, Project, Role, Workspace
from app.services.admin_config import ensure_provider_enabled
from app.services.audit import audit
from app.services.queue import enqueue
from app.services.quota import ensure_token_budget
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["resources"])


def _ok(data): return {"success": True, "data": data}
def _nf(what): return AppError(404, "RESOURCE_NOT_FOUND", f"{what} introuvable")


async def _owned(db, model, id_, org_id, what):
    obj = (await db.execute(select(model).where(model.id == id_, model.organization_id == org_id,
                                                model.deleted_at.is_(None)))).scalar_one_or_none()
    if not obj:
        raise _nf(what)
    return obj


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProjectIn(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str
    description: str = ""
    system_prompt: str = Field(min_length=1, max_length=8000)
    model: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    tools: list[str] = []


class ExecutionIn(BaseModel):
    project_id: uuid.UUID
    mission: str = Field(min_length=5, max_length=8000)
    workflow: list[dict] | None = Field(default=None, max_length=30)


@router.get("/workspaces")
async def list_workspaces(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workspace).where(Workspace.organization_id == c.org_id,
                                                     Workspace.deleted_at.is_(None)))).scalars()
    return _ok([{"id": str(w.id), "name": w.name} for w in rows])


@router.post("/workspaces", status_code=201)
async def create_workspace(b: WorkspaceIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    w = Workspace(organization_id=c.org_id, name=b.name); db.add(w); await db.commit()
    return _ok({"id": str(w.id), "name": w.name})


@router.get("/projects")
async def list_projects(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db),
                        limit: int = Query(50, le=200), offset: int = Query(0, ge=0)):
    rows = (await db.execute(select(Project).where(Project.organization_id == c.org_id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc()).limit(limit).offset(offset))).scalars()
    return _ok([{"id": str(p.id), "name": p.name, "workspace_id": str(p.workspace_id),
                 "description": p.description} for p in rows])


@router.post("/projects", status_code=201)
async def create_project(b: ProjectIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    await _owned(db, Workspace, b.workspace_id, c.org_id, "Espace de travail")  # empêche un workspace d'une autre org
    p = Project(organization_id=c.org_id, workspace_id=b.workspace_id, name=b.name, description=b.description)
    db.add(p); await db.commit()
    return _ok({"id": str(p.id), "name": p.name})


@router.get("/agents")
async def list_agents(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Agent).where(Agent.organization_id == c.org_id, Agent.deleted_at.is_(None)))).scalars()
    return _ok([{"id": str(a.id), "name": a.name, "role": a.role, "model": a.model,
                 "temperature": a.temperature, "status": a.status} for a in rows])


def _check_role(role: str):
    if role not in ROLES:
        raise AppError(422, "VALIDATION_ERROR", f"role doit être l'un de: {', '.join(ROLES)}")


@router.post("/agents", status_code=201)
async def create_agent(b: AgentIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER); _check_role(b.role)
    a = Agent(organization_id=c.org_id, **{**b.model_dump(), "model": b.model or get_settings().default_model})
    db.add(a); await db.commit()
    return _ok({"id": str(a.id)})


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: uuid.UUID, b: AgentIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER); _check_role(b.role)
    a = await _owned(db, Agent, agent_id, c.org_id, "Agent")
    for k, v in b.model_dump().items():
        if k != "model" or v:
            setattr(a, k, v)
    await db.commit()
    return _ok({"id": str(a.id)})


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    from sqlalchemy.sql import func
    c.require(Role.ADMIN)
    a = await _owned(db, Agent, agent_id, c.org_id, "Agent")
    a.deleted_at = func.now(); await db.commit()


@router.post("/executions", status_code=202)
async def create_execution(b: ExecutionIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    await _owned(db, Project, b.project_id, c.org_id, "Projet")
    await ensure_token_budget(db, c.org_id)
    await ensure_provider_enabled(db)
    if b.workflow:
        from app.orchestration.engine import GraphError, graph_from_workflow
        try:
            graph_from_workflow(b.workflow)
        except (GraphError, KeyError) as ex:
            raise AppError(422, "INVALID_WORKFLOW", str(ex))
    e = Execution(organization_id=c.org_id, project_id=b.project_id, created_by=c.user.id, mission=b.mission,
                  workflow=b.workflow)
    db.add(e); await db.flush()
    await audit(db, "execution.create", user_id=c.user.id, org_id=c.org_id, resource="execution", resource_id=e.id, request=request)
    await db.commit()
    await enqueue(str(e.id))  # l'orchestration tourne dans le worker, jamais dans la requête HTTP
    return _ok({"id": str(e.id), "status": e.status})


@router.get("/executions")
async def list_executions(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db),
                          limit: int = Query(30, le=100), offset: int = Query(0, ge=0)):
    rows = (await db.execute(select(Execution).where(Execution.organization_id == c.org_id, Execution.deleted_at.is_(None))
            .order_by(Execution.created_at.desc()).limit(limit).offset(offset))).scalars()
    return _ok([{"id": str(e.id), "mission": e.mission[:160], "status": e.status, "tokens": e.tokens,
                 "created_at": e.created_at.isoformat()} for e in rows])


@router.get("/executions/{exec_id}")
async def get_execution(exec_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    e = await _owned(db, Execution, exec_id, c.org_id, "Exécution")
    return _ok({"id": str(e.id), "status": e.status, "mission": e.mission, "result": e.result,
                "error": e.error, "tokens": e.tokens})


@router.get("/executions/{exec_id}/events")
async def get_events(exec_id: uuid.UUID, after: int = Query(0, ge=0), c: Ctx = Depends(ctx),
                     db: AsyncSession = Depends(get_db)):
    """Interrogation incrémentale (?after=seq) : compatible serverless, sans connexion longue."""
    await _owned(db, Execution, exec_id, c.org_id, "Exécution")
    rows = (await db.execute(select(ExecutionEvent).where(ExecutionEvent.execution_id == exec_id,
            ExecutionEvent.seq > after).order_by(ExecutionEvent.seq).limit(500))).scalars()
    return _ok([{"seq": r.seq, "kind": r.kind, "data": r.data} for r in rows])


@router.post("/executions/{exec_id}/cancel")
async def cancel_execution(exec_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    e = await _owned(db, Execution, exec_id, c.org_id, "Exécution")
    if e.status in ("COMPLETED", "FAILED", "CANCELLED"):
        raise AppError(409, "ALREADY_FINISHED", "Cette exécution est déjà terminée")
    e.status = "CANCELLING"
    await audit(db, "execution.cancel", user_id=c.user.id, org_id=c.org_id, resource="execution", resource_id=e.id)
    await db.commit()  # le worker consulte ce statut entre deux couches
    return _ok({"id": str(e.id), "status": e.status})
