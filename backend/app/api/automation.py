"""Équipes, agents personnalisés, workflows, déclencheurs, événements, approbations humaines, RAG, tableau de bord."""
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.catalog import agent_from_dict
from app.catalog.model import ROLE_KINDS, Modality, Permission
from app.core.crypto import get_secretbox
from app.core.db import get_db
from app.core.errors import AppError
from app.models.entities import (AiSettings, ApprovalRequest, CustomAgent, Execution, ProviderConfig, Role, Team, UsageRecord,
                                 Workflow, WorkflowRun, WorkflowTrigger)
from app.services import assembly as A
from app.services.audit import audit
from app.tools.builtin import default_registry
from app.workflows import triggers as T
from app.workflows.runner import WorkflowError, validate_definition
from .common import ok, owned
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["automation"])
NAME_RE = re.compile(r"^[A-Za-z0-9][\w .'-]{1,79}$")
TOOL_NAMES = {t.name for t in default_registry(".").all()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- équipes (§37) ---------------------------------------------------------------------------------------------------------
class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field("", max_length=1000)
    agent_ids: list[str] = Field(min_length=1, max_length=100)


def _team_dto(t: Team) -> dict:
    return {"id": str(t.id), "name": t.name, "description": t.description, "agent_ids": t.agent_ids}


async def _check_agents(db, org_id, ids: list[str]) -> None:
    cat = await A.get_org_catalog(db, org_id)
    unknown = [i for i in ids if cat.get(i) is None]
    if unknown:
        raise AppError(422, "UNKNOWN_AGENTS", f"Agents inconnus : {', '.join(unknown[:10])}")


@router.get("/teams")
async def list_teams(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Team).where(Team.organization_id == c.org_id, Team.deleted_at.is_(None))
                             .order_by(Team.name))).scalars().all()
    return ok([_team_dto(t) for t in rows])


@router.post("/teams", status_code=201)
async def create_team(b: TeamIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    await _check_agents(db, c.org_id, b.agent_ids)
    if (await db.execute(select(Team.id).where(Team.organization_id == c.org_id, Team.name == b.name))).first():
        raise AppError(409, "TEAM_EXISTS", "Une équipe porte déjà ce nom")
    t = Team(organization_id=c.org_id, name=b.name, description=b.description, agent_ids=list(dict.fromkeys(b.agent_ids)))
    db.add(t); await db.flush()
    await audit(db, "team.create", user_id=c.user.id, org_id=c.org_id, resource="team", resource_id=t.id, request=request)
    await db.commit()
    return ok(_team_dto(t))


@router.put("/teams/{team_id}")
async def update_team(team_id: uuid.UUID, b: TeamIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    t = await owned(db, Team, team_id, c.org_id, "Équipe")
    await _check_agents(db, c.org_id, b.agent_ids)
    t.name, t.description, t.agent_ids = b.name, b.description, list(dict.fromkeys(b.agent_ids))
    await db.commit()
    return ok(_team_dto(t))


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(team_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    (await owned(db, Team, team_id, c.org_id, "Équipe")).deleted_at = func.now()
    await db.commit()


# ---- agents personnalisés / Agent Builder (§36) -------------------------------------------------------------------------------
class CustomAgentIn(BaseModel):
    agent_id: str = Field(pattern=r"^custom-[a-z0-9][a-z0-9-]{1,30}$")
    name: str = Field(min_length=2, max_length=80)
    description: str = Field("", max_length=1000)
    category: str = Field("Custom", max_length=60)
    role_kind: str = "specialist"
    skills: list[str] = Field(default_factory=list, max_length=30)
    keywords: list[str] = Field(default_factory=list, max_length=40)
    needs: list[str] = Field(default_factory=lambda: ["chat"], max_length=10)
    tools: dict[str, str] = Field(default_factory=dict, max_length=20)   # outil → NONE|READ|WRITE|EXECUTE
    inputs: list[str] = Field(default_factory=lambda: ["text"])
    outputs: list[str] = Field(default_factory=lambda: ["text"])
    instructions: str = Field("", max_length=8000)                       # prompt système
    est_tokens: int = Field(4000, ge=100, le=200000)
    sensitive: bool = False
    local_ok: bool = True
    cloud_ok: bool = True
    enabled: bool = True

    @field_validator("role_kind")
    @classmethod
    def _rk(cls, v):
        if v not in ROLE_KINDS:
            raise ValueError(f"role_kind : {', '.join(ROLE_KINDS)}")
        return v

    @field_validator("tools")
    @classmethod
    def _tools(cls, v):
        for n, p in v.items():
            if n not in TOOL_NAMES:
                raise ValueError(f"Outil inconnu : {n}")
            if p not in ("NONE", "READ", "WRITE", "EXECUTE"):
                raise ValueError("Niveau d'outil : NONE, READ, WRITE ou EXECUTE (ADMIN non accordable à un agent)")
        return v

    @field_validator("inputs", "outputs")
    @classmethod
    def _mods(cls, v):
        bad = [m for m in v if m not in {x.value for x in Modality}]
        if bad:
            raise ValueError(f"Modalités inconnues : {bad}")
        return v


def _agent_dto(row: CustomAgent) -> dict:
    return {"id": row.agent_id, "enabled": row.enabled, **{k: v for k, v in row.definition.items() if k != "id"}}


def _definition(b: CustomAgentIn) -> dict:
    d = {"id": b.agent_id, "name": b.name, "description": b.description, "category": b.category, "role_kind": b.role_kind,
         "domain": b.agent_id, "skills": b.skills or [f"custom.{b.agent_id}"], "keywords": b.keywords, "needs": b.needs,
         "tools": b.tools, "inputs": b.inputs, "outputs": b.outputs, "est_tokens": b.est_tokens, "sensitive": b.sensitive,
         "local_ok": b.local_ok, "cloud_ok": b.cloud_ok, "system_prompt": b.instructions or f"Tu es {b.name}.", "source": "custom"}
    try:
        agent_from_dict(d)
    except ValueError as e:
        raise AppError(422, "INVALID_AGENT", str(e))
    return d


@router.get("/custom-agents")
async def list_custom_agents(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CustomAgent).where(CustomAgent.organization_id == c.org_id,
                                                       CustomAgent.deleted_at.is_(None)))).scalars().all()
    return ok([_agent_dto(r) for r in rows])


@router.post("/custom-agents", status_code=201)
async def create_custom_agent(b: CustomAgentIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    if (await db.execute(select(CustomAgent.id).where(CustomAgent.organization_id == c.org_id,
                                                      CustomAgent.agent_id == b.agent_id))).first():
        raise AppError(409, "AGENT_EXISTS", "Un agent porte déjà cet identifiant")
    row = CustomAgent(organization_id=c.org_id, agent_id=b.agent_id, definition=_definition(b), enabled=b.enabled)
    db.add(row); await db.flush()
    await audit(db, "custom_agent.create", user_id=c.user.id, org_id=c.org_id, resource="custom_agent", resource_id=row.id,
                request=request, meta={"agent": b.agent_id, "tools": b.tools})
    await db.commit()
    A.invalidate_catalog(c.org_id)
    return ok(_agent_dto(row))


@router.put("/custom-agents/{agent_id}")
async def update_custom_agent(agent_id: str, b: CustomAgentIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    if b.agent_id != agent_id:
        raise AppError(422, "ID_MISMATCH", "L'identifiant ne peut pas être modifié")
    row = (await db.execute(select(CustomAgent).where(CustomAgent.organization_id == c.org_id, CustomAgent.agent_id == agent_id,
                                                      CustomAgent.deleted_at.is_(None)))).scalar_one_or_none()
    if not row:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Agent introuvable")
    row.definition, row.enabled = _definition(b), b.enabled
    await db.commit()
    A.invalidate_catalog(c.org_id)
    return ok(_agent_dto(row))


@router.delete("/custom-agents/{agent_id}", status_code=204)
async def delete_custom_agent(agent_id: str, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    row = (await db.execute(select(CustomAgent).where(CustomAgent.organization_id == c.org_id, CustomAgent.agent_id == agent_id,
                                                      CustomAgent.deleted_at.is_(None)))).scalar_one_or_none()
    if not row:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Agent introuvable")
    row.deleted_at = func.now()
    await db.commit()
    A.invalidate_catalog(c.org_id)


# ---- workflows (§25) -----------------------------------------------------------------------------------------------------------
class WorkflowIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field("", max_length=1000)
    definition: dict
    enabled: bool = True
    project_id: uuid.UUID | None = None


def _agent_refs(defn: dict) -> set[str]:
    out = set()
    for n in defn.get("nodes", []):
        if isinstance(n, dict):
            if n.get("type") == "agent":
                out.add(str(n.get("agent")))
            body = n.get("body")
            if isinstance(body, dict) and body.get("type") == "agent":
                out.add(str(body.get("agent")))
    return out


async def _validate_workflow(db, org_id, defn: dict) -> None:
    try:
        validate_definition(defn)
    except WorkflowError as e:
        raise AppError(422, "INVALID_WORKFLOW", str(e))
    cat = await A.get_org_catalog(db, org_id)
    from app.agents.roles import ROLES
    unknown = [a for a in _agent_refs(defn) if cat.get(a) is None and a not in ROLES]
    if unknown:
        raise AppError(422, "UNKNOWN_AGENTS", f"Agents inconnus : {', '.join(sorted(unknown))}")


def _wf_dto(w: Workflow) -> dict:
    return {"id": str(w.id), "name": w.name, "description": w.description, "definition": w.definition,
            "enabled": w.enabled, "project_id": str(w.project_id) if w.project_id else None}


@router.get("/workflows")
async def list_workflows(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workflow).where(Workflow.organization_id == c.org_id, Workflow.deleted_at.is_(None))
                             .order_by(Workflow.name))).scalars().all()
    return ok([_wf_dto(w) for w in rows])


@router.post("/workflows/validate")
async def validate_wf(defn: dict, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    await _validate_workflow(db, c.org_id, defn)
    return ok({"valid": True, "nodes": len(defn["nodes"])})


@router.post("/workflows", status_code=201)
async def create_workflow(b: WorkflowIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    await _validate_workflow(db, c.org_id, b.definition)
    if (await db.execute(select(Workflow.id).where(Workflow.organization_id == c.org_id, Workflow.name == b.name))).first():
        raise AppError(409, "WORKFLOW_EXISTS", "Un workflow porte déjà ce nom")
    w = Workflow(organization_id=c.org_id, name=b.name, description=b.description, definition=b.definition,
                 enabled=b.enabled, project_id=b.project_id)
    db.add(w); await db.flush()
    await audit(db, "workflow.create", user_id=c.user.id, org_id=c.org_id, resource="workflow", resource_id=w.id, request=request)
    await db.commit()
    return ok(_wf_dto(w))


@router.put("/workflows/{wid}")
async def update_workflow(wid: uuid.UUID, b: WorkflowIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    w = await owned(db, Workflow, wid, c.org_id, "Workflow")
    await _validate_workflow(db, c.org_id, b.definition)
    w.name, w.description, w.definition, w.enabled, w.project_id = b.name, b.description, b.definition, b.enabled, b.project_id
    await db.commit()
    return ok(_wf_dto(w))


@router.delete("/workflows/{wid}", status_code=204)
async def delete_workflow(wid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    (await owned(db, Workflow, wid, c.org_id, "Workflow")).deleted_at = func.now()
    await db.commit()


class RunIn(BaseModel):
    payload: dict = Field(default_factory=dict)


@router.post("/workflows/{wid}/run", status_code=202)
async def run_workflow(wid: uuid.UUID, b: RunIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    w = await owned(db, Workflow, wid, c.org_id, "Workflow")
    if not w.enabled:
        raise AppError(409, "WORKFLOW_DISABLED", "Ce workflow est désactivé")
    if len(json.dumps(b.payload)) > 100_000:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Données trop volumineuses")
    from app.services.quota import ensure_cost_budget
    await ensure_cost_budget(db, c.org_id, False)
    r = WorkflowRun(organization_id=c.org_id, workflow_id=w.id, created_by=c.user.id, trigger_type="manual",
                    payload={"type": "manual", **b.payload})
    db.add(r); await db.flush()
    await audit(db, "workflow.run", user_id=c.user.id, org_id=c.org_id, resource="workflow_run", resource_id=r.id, request=request)
    await db.commit()
    return ok({"run_id": str(r.id), "status": r.status})


def _run_dto(r: WorkflowRun, full: bool = False) -> dict:
    d = {"id": str(r.id), "workflow_id": str(r.workflow_id), "trigger_type": r.trigger_type, "status": r.status,
         "error": r.error, "created_at": r.created_at.isoformat() if r.created_at else None,
         "started_at": r.started_at.isoformat() if r.started_at else None,
         "finished_at": r.finished_at.isoformat() if r.finished_at else None}
    if full:
        d.update(payload=r.payload, node_states=r.node_states, output=r.output)
    return d


@router.get("/workflow-runs")
async def list_runs(workflow_id: uuid.UUID | None = None, status: str | None = None, limit: int = Query(30, le=100),
                    c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    q = select(WorkflowRun).where(WorkflowRun.organization_id == c.org_id)
    if workflow_id:
        q = q.where(WorkflowRun.workflow_id == workflow_id)
    if status:
        q = q.where(WorkflowRun.status == status.upper())
    rows = (await db.execute(q.order_by(WorkflowRun.created_at.desc()).limit(limit))).scalars().all()
    return ok([_run_dto(r) for r in rows])


@router.get("/workflow-runs/{rid}")
async def get_run(rid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    return ok(_run_dto(await owned(db, WorkflowRun, rid, c.org_id, "Exécution de workflow"), full=True))


@router.post("/workflow-runs/{rid}/cancel")
async def cancel_run(rid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    r = await owned(db, WorkflowRun, rid, c.org_id, "Exécution de workflow")
    if r.status == "PENDING":
        r.status, r.finished_at = "CANCELLED", func.now()
    elif r.status == "RUNNING":
        r.status = "CANCELLING"   # le worker s'arrête entre deux étapes
    else:
        raise AppError(409, "NOT_CANCELLABLE", "Cette exécution est déjà terminée")
    await db.commit()
    return ok({"status": r.status})


# ---- déclencheurs (§26) -------------------------------------------------------------------------------------------------------------
class TriggerIn(BaseModel):
    type: str
    config: dict = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in T.TRIGGER_TYPES or v == "manual":
            raise ValueError(f"Type : {', '.join(t for t in T.TRIGGER_TYPES if t != 'manual')}")
        return v

    @field_validator("config")
    @classmethod
    def _c(cls, v):
        if len(json.dumps(v)) > 4000:
            raise ValueError("Configuration trop volumineuse")
        flt = v.get("filter", {})
        if not isinstance(flt, dict) or len(flt) > 10:
            raise ValueError("filter : objet de 10 clés maximum")
        return v


def _trig_dto(t: WorkflowTrigger, secret: str | None = None) -> dict:
    d = {"id": str(t.id), "workflow_id": str(t.workflow_id), "type": t.type, "config": t.config, "enabled": t.enabled,
         "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
         "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None}
    if t.type in ("webhook", "github"):
        d["hook_path"] = f"/api/hooks/{t.id}"
    if secret:
        d["secret"] = secret  # affiché UNE seule fois
    return d


@router.get("/workflows/{wid}/triggers")
async def list_triggers(wid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    await owned(db, Workflow, wid, c.org_id, "Workflow")
    rows = (await db.execute(select(WorkflowTrigger).where(WorkflowTrigger.workflow_id == wid, WorkflowTrigger.organization_id == c.org_id,
                                                           WorkflowTrigger.deleted_at.is_(None)))).scalars().all()
    return ok([_trig_dto(t) for t in rows])


@router.post("/workflows/{wid}/triggers", status_code=201)
async def create_trigger(wid: uuid.UUID, b: TriggerIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    await owned(db, Workflow, wid, c.org_id, "Workflow")
    t = WorkflowTrigger(organization_id=c.org_id, workflow_id=wid, type=b.type, config=b.config, enabled=b.enabled)
    secret = None
    if b.type == "schedule":
        try:
            t.next_run_at = T.next_run(str(b.config.get("cron", "")), _now())
        except T.CronError as e:
            raise AppError(422, "INVALID_CRON", str(e))
    elif b.type in ("webhook", "github"):
        secret = secrets.token_urlsafe(32)
        t.secret_enc = get_secretbox().encrypt(secret, aad=str(c.org_id))
    db.add(t); await db.flush()
    await audit(db, "trigger.create", user_id=c.user.id, org_id=c.org_id, resource="trigger", resource_id=t.id,
                request=request, meta={"type": b.type})
    await db.commit()
    return ok(_trig_dto(t, secret))


@router.delete("/triggers/{tid}", status_code=204)
async def delete_trigger(tid: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    (await owned(db, WorkflowTrigger, tid, c.org_id, "Déclencheur")).deleted_at = func.now()
    await db.commit()


@router.post("/hooks/{trigger_id}", status_code=202)
async def incoming_hook(trigger_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
                        x_aiw_timestamp: str | None = Header(None), x_aiw_signature: str | None = Header(None),
                        x_hub_signature_256: str | None = Header(None), x_github_event: str | None = Header(None)):
    """Webhook public. Toute défaillance renvoie le même 401 : on ne révèle ni l'existence ni le type du déclencheur."""
    body = await request.body()
    if len(body) > 256_000:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Corps trop volumineux")
    denied = AppError(401, "INVALID_SIGNATURE", "Signature invalide")
    t = await db.get(WorkflowTrigger, trigger_id)
    if not t or t.deleted_at or not t.enabled or t.type not in ("webhook", "github") or not t.secret_enc:
        raise denied
    w = await db.get(Workflow, t.workflow_id)
    if not w or w.deleted_at or not w.enabled:
        raise denied
    secret = get_secretbox().decrypt(t.secret_enc, aad=str(t.organization_id))
    good = (T.verify_github(secret, body, x_hub_signature_256) if t.type == "github"
            else T.verify_webhook(secret, body, x_aiw_timestamp, x_aiw_signature))
    if not good:
        raise denied
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {"raw": body[:2000].decode("utf-8", "replace")}
    if t.type == "github":
        ref = str(data.get("ref", "")) if isinstance(data, dict) else ""
        event = {"type": "github", "event": x_github_event or "", "repo": (data.get("repository") or {}).get("full_name", "")
                 if isinstance(data, dict) else "", "branch": ref.removeprefix("refs/heads/"), "payload": data}
        if not T.matches("github", t.config or {}, event):
            return ok({"accepted": False, "reason": "filtré"})
    else:
        event = {"type": "webhook", "body": data}
    since = _now() - timedelta(minutes=1)
    recent = (await db.execute(select(func.count()).select_from(WorkflowRun).where(
        WorkflowRun.workflow_id == w.id, WorkflowRun.created_at >= since))).scalar_one()
    if recent >= A.MAX_RUNS_PER_MINUTE:
        raise AppError(429, "RATE_LIMITED", "Trop de déclenchements pour ce workflow")
    r = WorkflowRun(organization_id=t.organization_id, workflow_id=w.id, trigger_type=t.type, payload=event)
    db.add(r); t.last_run_at = _now(); await db.flush()
    run_id = str(r.id)
    await db.commit()
    return ok({"accepted": True, "run_id": run_id})


class EventIn(BaseModel):
    type: str
    fields: dict = Field(default_factory=dict, max_length=20)

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in ("api_event", "agent_event", "db_event", "file_added"):
            raise ValueError("type : api_event, agent_event, db_event ou file_added")
        return v

    @field_validator("fields")
    @classmethod
    def _f(cls, v):
        if any(not isinstance(x, (str, int, float, bool)) or len(str(x)) > 500 for x in v.values()):
            raise ValueError("Valeurs scalaires (500 caractères max) uniquement")
        return v


@router.post("/events", status_code=202)
async def post_event(b: EventIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Événement applicatif (API, base de données, agent) : lance les workflows dont un déclencheur correspond."""
    c.require(Role.MEMBER)
    n = await A.fire_event(db, c.org_id, {"type": b.type, **b.fields})
    await db.commit()
    return ok({"triggered": n})


# ---- validation humaine (§22) ------------------------------------------------------------------------------------------------------
class DecisionIn(BaseModel):
    approved: bool


def _appr_dto(a: ApprovalRequest) -> dict:
    return {"id": str(a.id), "agent": a.agent, "tool": a.tool, "action": a.action, "summary": a.summary, "status": a.status,
            "execution_id": str(a.execution_id) if a.execution_id else None,
            "workflow_run_id": str(a.workflow_run_id) if a.workflow_run_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/approvals")
async def list_approvals(status: str = "PENDING", limit: int = Query(50, le=200), c: Ctx = Depends(ctx),
                         db: AsyncSession = Depends(get_db)):
    q = select(ApprovalRequest).where(ApprovalRequest.organization_id == c.org_id, ApprovalRequest.status == status.upper())
    rows = (await db.execute(q.order_by(ApprovalRequest.created_at.desc()).limit(limit))).scalars().all()
    return ok([_appr_dto(a) for a in rows])


@router.post("/approvals/{aid}/decision")
async def decide(aid: uuid.UUID, b: DecisionIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    a = await owned(db, ApprovalRequest, aid, c.org_id, "Demande")
    if a.status != "PENDING":
        raise AppError(409, "ALREADY_DECIDED", f"Demande déjà {a.status.lower()}")
    a.status, a.decided_by, a.decided_at = ("APPROVED" if b.approved else "DENIED"), c.user.id, _now()
    await audit(db, "approval.decide", user_id=c.user.id, org_id=c.org_id, resource="approval", resource_id=a.id, request=request,
                meta={"approved": b.approved, "tool": a.tool, "action": a.action})
    await db.commit()
    return ok(_appr_dto(a))


# ---- RAG (§24) ---------------------------------------------------------------------------------------------------------------------
class RagIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(5, ge=1, le=10)
    project_id: uuid.UUID | None = None


@router.post("/rag/search")
async def rag_search(b: RagIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    _, providers, settings = await A.load_providers(db, c.org_id, None)
    hits = await A.rag_search(db, c.org_id, b.query, A.make_embedder(settings, providers, c.org_id), b.k, b.project_id)
    await db.commit()  # persiste les embeddings calculés à la volée
    return ok(hits)


@router.post("/rag/reindex")
async def rag_reindex(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Recalcule les embeddings manquants ou d'un autre modèle (par lots de 200, 10 lots par appel)."""
    c.require(Role.ADMIN)
    _, providers, settings = await A.load_providers(db, c.org_id, None)
    emb, done = A.make_embedder(settings, providers, c.org_id), 0
    for _ in range(10):
        n = await A.ensure_embeddings(db, c.org_id, emb, 200)
        done += n
        await db.flush()
        if n < 200:
            break
    await db.commit()
    return ok({"embedded": done, "model": emb.name, "more": done >= 2000})


# ---- tableau de bord (§34) ---------------------------------------------------------------------------------------------------------------
@router.get("/dashboard/overview")
async def dashboard_overview(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    org, now = c.org_id, _now()
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    ex = dict((await db.execute(select(Execution.status, func.count()).where(
        Execution.organization_id == org, Execution.created_at >= now - timedelta(days=30), Execution.deleted_at.is_(None))
        .group_by(Execution.status))).all())
    wf = dict((await db.execute(select(WorkflowRun.status, func.count()).where(
        WorkflowRun.organization_id == org, WorkflowRun.created_at >= week).group_by(WorkflowRun.status))).all())
    tot = (await db.execute(select(func.coalesce(func.sum(UsageRecord.tokens), 0), func.coalesce(func.sum(UsageRecord.tokens_in), 0),
                                   func.coalesce(func.sum(UsageRecord.tokens_out), 0), func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                                   func.count()).where(UsageRecord.organization_id == org, UsageRecord.created_at >= month))).one()
    by_model = (await db.execute(select(UsageRecord.model, func.sum(UsageRecord.tokens), func.sum(UsageRecord.cost_usd)).where(
        UsageRecord.organization_id == org, UsageRecord.created_at >= month).group_by(UsageRecord.model)
        .order_by(func.sum(UsageRecord.cost_usd).desc(), func.sum(UsageRecord.tokens).desc()).limit(8))).all()
    providers = (await db.execute(select(ProviderConfig.name, ProviderConfig.kind, ProviderConfig.enabled, ProviderConfig.local)
                                  .where(ProviderConfig.organization_id == org))).all()
    pending = (await db.execute(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.organization_id == org, ApprovalRequest.status == "PENDING"))).scalar_one()
    errors = (await db.execute(select(Execution.id, Execution.error, Execution.created_at).where(
        Execution.organization_id == org, Execution.status == "FAILED").order_by(Execution.created_at.desc()).limit(5))).all()
    budget = (await db.execute(select(AiSettings.monthly_budget_usd).where(AiSettings.organization_id == org))).scalar_one_or_none()
    from .bridge import get_broker, scope_of
    bridge = await get_broker().status(scope_of(c))
    return ok({
        "executions_30d": ex, "workflow_runs_7d": wf, "pending_approvals": pending,
        "usage_month": {"tokens": int(tot[0]), "tokens_in": int(tot[1]), "tokens_out": int(tot[2]), "cost_usd": round(float(tot[3]), 4),
                        "calls": int(tot[4]), "budget_usd": budget,
                        "by_model": [{"model": m, "tokens": int(t or 0), "cost_usd": round(float(cst or 0), 4)} for m, t, cst in by_model]},
        "providers": [{"name": n, "kind": k, "enabled": e, "local": lo} for n, k, e, lo in providers],
        "bridge": {"online": bridge is not None, **(bridge or {})},
        "recent_errors": [{"id": str(i), "error": (er or "")[:160], "at": at.isoformat() if at else None} for i, er, at in errors]})
