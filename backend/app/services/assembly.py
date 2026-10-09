"""Assemblage par organisation (accès base de données) : catalogue + agents personnalisés + équipe, fournisseurs,
embeddings/RAG, approbations humaines, outils sur les fichiers du projet, événements et déclencheurs.
Ces fonctions sont partagées par l'API et le worker."""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from app.catalog.catalog import Catalog, agent_from_dict
from app.catalog.model import AgentDef, Permission
from app.core.crypto import CryptoError, get_secretbox
from app.llm.providers import PRESETS
from app.models.entities import (AiSettings, ApprovalRequest, CustomAgent, FileChunk, Notification, ProviderConfig,
                                 StoredFile, Team, Workflow, WorkflowRun, WorkflowTrigger)
from app.rag.embedder import HashingEmbedder, OpenAICompatEmbedder
from app.rag.search import Doc, hybrid_search
from app.services.runtime_factory import ProviderCfg
from app.storage.backends import make_storage
from app.storage.paths import UnsafePath, safe_path
from app.tools.registry import Action, ToolBox, ToolDef, ToolError
from app.workflows.triggers import matches, next_run

_BASE: Catalog | None = None
MAX_RUNS_PER_MINUTE = 20      # disjoncteur anti-boucle : un workflow qui se redéclenche lui-même est freiné


def base_catalog() -> Catalog:
    global _BASE
    if _BASE is None:
        _BASE = Catalog.default()
    return _BASE


# ---- catalogue, équipes ----------------------------------------------------------------------------------------------
async def load_catalog(db, org_id: uuid.UUID, team_id: uuid.UUID | None = None) -> Catalog:
    agents: list[AgentDef] = list(base_catalog())
    rows = (await db.execute(select(CustomAgent).where(CustomAgent.organization_id == org_id, CustomAgent.enabled.is_(True),
                                                       CustomAgent.deleted_at.is_(None)))).scalars().all()
    for r in rows:
        try:
            agents.append(agent_from_dict({**r.definition, "id": r.agent_id}))
        except ValueError:
            continue  # définition devenue invalide : ignorée plutôt que de bloquer toute l'organisation
    if team_id:
        team = await db.get(Team, team_id)
        if team and team.organization_id == org_id and team.deleted_at is None:
            ids = set(team.agent_ids or [])
            agents = [a for a in agents if a.id in ids]
    return Catalog(agents)


_ORG_CACHE: dict[uuid.UUID, tuple[float, Catalog]] = {}
_CACHE_TTL_S = 30.0


async def get_org_catalog(db, org_id: uuid.UUID) -> Catalog:
    """Catalogue de l'organisation (intégré + personnalisé), mis en cache 30 s ; invalidé à chaque modification."""
    import time
    hit = _ORG_CACHE.get(org_id)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    cat = await load_catalog(db, org_id)
    _ORG_CACHE[org_id] = (time.monotonic(), cat)
    return cat


def invalidate_catalog(org_id: uuid.UUID) -> None:
    _ORG_CACHE.pop(org_id, None)


# ---- fournisseurs, embeddings ------------------------------------------------------------------------------------------
async def load_providers(db, org_id: uuid.UUID, user_id: uuid.UUID | None, broker=None):
    """(cfgs activés, tous les ProviderConfig par nom, AiSettings). Les clés sont déchiffrées en mémoire seulement."""
    rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.organization_id == org_id))).scalars().all()
    settings = (await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))).scalar_one_or_none()
    box = get_secretbox() if any(p.api_key_enc for p in rows) else None
    cfgs = []
    for p in rows:
        if not p.enabled:
            continue
        opts = dict(p.options or {})
        if p.kind == "bridge":
            if broker is None or user_id is None:
                continue
            opts.update(broker=broker, scope=f"{org_id}:{user_id}")
        try:
            key = box.decrypt(p.api_key_enc, aad=str(org_id)) if p.api_key_enc else None
        except CryptoError:
            continue  # clé de chiffrement changée : ce fournisseur est inutilisable tant que la clé API n'est pas ressaisie
        cfgs.append(ProviderCfg(p.kind, p.name, p.base_url, key, p.models, True, p.priority,
                                p.local or p.kind == "bridge", opts))
    return cfgs, {p.name: p for p in rows}, settings


def make_embedder(settings: AiSettings | None, providers: dict[str, ProviderConfig], org_id: uuid.UUID):
    """Embeddings du fournisseur choisi (compatible OpenAI) ; sinon embeddings lexicaux locaux (repli hors ligne)."""
    if settings and settings.embedding_provider and settings.embedding_model:
        p = providers.get(settings.embedding_provider)
        base = (p.base_url or PRESETS.get(p.kind, {}).get("base_url")) if p else None
        if p and base:
            key = get_secretbox().decrypt(p.api_key_enc, aad=str(org_id)) if p.api_key_enc else None
            return OpenAICompatEmbedder(base, settings.embedding_model, key)
    return HashingEmbedder()


async def ensure_embeddings(db, org_id: uuid.UUID, embedder, limit: int = 200) -> int:
    """Calcule les embeddings manquants (ou d'un autre modèle) pour au plus `limit` passages."""
    q = select(FileChunk).where(FileChunk.organization_id == org_id,
                                (FileChunk.embedding.is_(None)) | (FileChunk.embed_model != embedder.name)).limit(limit)
    chunks = (await db.execute(q)).scalars().all()
    if not chunks:
        return 0
    vecs = await embedder.embed([c.content for c in chunks])
    for c, v in zip(chunks, vecs):
        c.embedding, c.embed_model = v, embedder.name
    return len(chunks)


async def rag_search(db, org_id: uuid.UUID, query: str, embedder, k: int = 5, project_id: uuid.UUID | None = None) -> list[dict]:
    await ensure_embeddings(db, org_id, embedder)
    q = select(FileChunk, StoredFile.path).join(StoredFile, FileChunk.file_id == StoredFile.id).where(
        FileChunk.organization_id == org_id, StoredFile.deleted_at.is_(None))
    if project_id:
        q = q.where(StoredFile.project_id == project_id)
    rows = (await db.execute(q.limit(20000))).all()
    docs = [Doc(c.id, c.content, c.embedding if c.embed_model == embedder.name else None, {"path": path, "idx": c.idx})
            for c, path in rows]
    qvec = (await embedder.embed([query]))[0]
    return [{"path": h.doc.meta["path"], "chunk": h.doc.meta["idx"], "score": round(h.score, 4), "text": h.doc.text[:1500]}
            for h in hybrid_search(query, qvec, docs, k)]


# ---- validation humaine -----------------------------------------------------------------------------------------------
class DbApprover:
    """Dépose une demande en base, notifie, et attend la décision d'un membre (délai dépassé = refus)."""

    def __init__(self, maker, org_id: uuid.UUID, notify_user: uuid.UUID | None = None, *, execution_id=None, run_id=None,
                 timeout_s: float = 600.0, poll_s: float = 1.0, emit=None):
        self.maker, self.org_id, self.notify_user = maker, org_id, notify_user
        self.execution_id, self.run_id, self.timeout_s, self.poll_s, self.emit = execution_id, run_id, timeout_s, poll_s, emit

    async def request(self, req) -> bool:
        async with self.maker() as s:
            row = ApprovalRequest(organization_id=self.org_id, execution_id=self.execution_id, workflow_run_id=self.run_id,
                                  agent=req.agent, tool=req.tool, action=req.action, summary=req.summary[:2000])
            s.add(row)
            if self.notify_user:
                s.add(Notification(user_id=self.notify_user, organization_id=self.org_id,
                                   title="Validation requise", body=req.summary[:140]))
            await s.commit()
            rid = row.id
        if self.emit:
            await self.emit("approval.requested", {"id": str(rid), "tool": req.tool, "action": req.action, "summary": req.summary[:300]})
        waited = 0.0
        while waited < self.timeout_s:
            await asyncio.sleep(self.poll_s)
            waited += self.poll_s
            async with self.maker() as s:
                row = await s.get(ApprovalRequest, rid)
                if row.status in ("APPROVED", "DENIED"):
                    return row.status == "APPROVED"
        async with self.maker() as s:
            await s.execute(update(ApprovalRequest).where(ApprovalRequest.id == rid, ApprovalRequest.status == "PENDING")
                            .values(status="EXPIRED"))
            await s.commit()
        return False


# ---- outils branchés sur les fichiers du projet --------------------------------------------------------------------------
def project_files_tool(maker, org_id: uuid.UUID, user_id: uuid.UUID, project_id: uuid.UUID) -> ToolDef:
    from app.services.projectfiles import write_file

    def clean(path: str) -> str:
        try:
            return safe_path(path)
        except UnsafePath as e:
            raise ToolError(str(e)) from e

    async def _file(s, path: str):
        return (await s.execute(select(StoredFile).where(
            StoredFile.organization_id == org_id, StoredFile.project_id == project_id, StoredFile.path == clean(path),
            StoredFile.deleted_at.is_(None)))).scalar_one_or_none()

    async def read(path: str) -> str:
        async with maker() as s:
            f = await _file(s, path)
            if f is None or f.size > 1_000_000:
                raise ToolError("Fichier introuvable ou trop volumineux")
            return (await make_storage().get(f.storage_key)).decode("utf-8", "replace")

    async def ls(path: str = ".") -> list[str]:
        prefix = "" if path in (".", "") else clean(path).rstrip("/") + "/"
        async with maker() as s:
            paths = (await s.execute(select(StoredFile.path).where(
                StoredFile.organization_id == org_id, StoredFile.project_id == project_id,
                StoredFile.deleted_at.is_(None)).limit(2000))).scalars().all()
        return sorted(p for p in paths if p.startswith(prefix))[:500]

    async def write(path: str, content: str) -> str:
        async with maker() as s:
            await write_file(s, org_id, user_id, project_id, clean(path), content.encode())
            await s.commit()
        return f"{len(content)} caractères écrits dans {path}"

    async def delete(path: str) -> str:
        async with maker() as s:
            f = await _file(s, path)
            if f is None:
                raise ToolError("Fichier introuvable")
            f.deleted_at = func.now()
            await s.commit()
        return f"{path} supprimé"
    return ToolDef("filesystem", "Fichiers du projet (stockage de l'organisation)", {
        "read": Action(Permission.READ, read, description="Lire un fichier texte"),
        "list": Action(Permission.READ, ls, description="Lister les fichiers (préfixe optionnel)"),
        "write": Action(Permission.WRITE, write, description="Écrire un fichier"),
        "delete": Action(Permission.WRITE, delete, requires_approval=True, description="Supprimer (validation humaine)")})


def toolbox_factory(registry, approver, audit):
    """AgentDef → ToolBox limitée aux outils DÉCLARÉS par cet agent (jamais au-delà de EXECUTE)."""
    def make(agent: AgentDef) -> ToolBox | None:
        grants = {n: Permission(min(p, int(Permission.EXECUTE))) for n, p in agent.tools}
        return ToolBox(registry, grants, approver=approver, audit=audit, agent=agent.id) if grants else None
    return make


# ---- événements, déclencheurs, file de workflows ----------------------------------------------------------------------------
async def fire_event(db, org_id: uuid.UUID, event: dict) -> int:
    """Crée une exécution de workflow pour chaque déclencheur correspondant. Appelé dans la transaction de l'appelant."""
    rows = (await db.execute(select(WorkflowTrigger, Workflow).join(Workflow, WorkflowTrigger.workflow_id == Workflow.id).where(
        WorkflowTrigger.organization_id == org_id, WorkflowTrigger.type == event.get("type"), WorkflowTrigger.enabled.is_(True),
        WorkflowTrigger.deleted_at.is_(None), Workflow.enabled.is_(True), Workflow.deleted_at.is_(None)))).all()
    created, since = 0, datetime.now(timezone.utc) - timedelta(minutes=1)
    for trig, wf in rows:
        if not matches(trig.type, trig.config or {}, event):
            continue
        recent = (await db.execute(select(func.count()).select_from(WorkflowRun).where(
            WorkflowRun.workflow_id == wf.id, WorkflowRun.created_at >= since))).scalar_one()
        if recent >= MAX_RUNS_PER_MINUTE:
            continue
        db.add(WorkflowRun(organization_id=org_id, workflow_id=wf.id, trigger_type=trig.type, payload=event))
        trig.last_run_at = datetime.now(timezone.utc)
        created += 1
    return created


async def schedule_tick(maker, now: datetime | None = None) -> int:
    """Déclenche les workflows planifiés échus et programme leur prochaine échéance."""
    now = now or datetime.now(timezone.utc)
    n = 0
    async with maker() as s:
        rows = (await s.execute(select(WorkflowTrigger, Workflow).join(Workflow, WorkflowTrigger.workflow_id == Workflow.id).where(
            WorkflowTrigger.type == "schedule", WorkflowTrigger.enabled.is_(True), WorkflowTrigger.deleted_at.is_(None),
            WorkflowTrigger.next_run_at <= now, Workflow.enabled.is_(True), Workflow.deleted_at.is_(None))
            .limit(50).with_for_update(skip_locked=True, of=WorkflowTrigger))).all()
        for trig, wf in rows:
            try:
                nxt = next_run(trig.config.get("cron", ""), now)
            except ValueError:
                trig.enabled = False  # expression devenue invalide : on désactive plutôt que de boucler
                continue
            s.add(WorkflowRun(organization_id=trig.organization_id, workflow_id=wf.id, trigger_type="schedule",
                              payload={"type": "schedule", "scheduled_for": trig.next_run_at.isoformat() if trig.next_run_at else ""}))
            trig.last_run_at, trig.next_run_at = now, nxt
            n += 1
        await s.commit()
    return n


async def claim_next_run(maker) -> uuid.UUID | None:
    """Réserve atomiquement la plus ancienne exécution PENDING (sûr avec plusieurs workers)."""
    async with maker() as s:
        rid = (await s.execute(select(WorkflowRun.id).where(WorkflowRun.status == "PENDING")
                               .order_by(WorkflowRun.created_at).limit(1))).scalar_one_or_none()
        if rid is None:
            return None
        res = await s.execute(update(WorkflowRun).where(WorkflowRun.id == rid, WorkflowRun.status == "PENDING")
                              .values(status="RUNNING", started_at=func.now()))
        await s.commit()
        return rid if res.rowcount == 1 else None
