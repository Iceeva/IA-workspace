"""Worker : consomme la file Redis et exécute l'orchestration hors de toute requête HTTP.
Persiste événements, tâches, messages inter-agents, usage, fichiers du Code Agent, mémoire de projet, notifications."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import session_maker
from app.llm.providers import get_provider
from app.core.crypto import get_secretbox
from app.memory.store import DBMemoryStore
from app.models.entities import (Agent, AgentMessage, AiSettings, Execution, ExecutionEvent, Notification,
                                 ProviderConfig, Task, TaskDependency, UsageRecord)
from app.orchestration.engine import ExecutionCancelled, Orchestrator, graph_from_workflow
from app.services.admin_config import ensure_provider_enabled
from app.services.budget import cost_usd
from app.services.codefs import make_diff, parse_file_blocks
from app.services.projectfiles import write_file
from app.services.queue import QUEUE, client
from app.services.runtime_factory import ProviderCfg, build_runtime, prefs_from_settings
from app.services.sandbox import SandboxUnavailable, run_code
from app.utils.logging import CTX, setup_logging

setup_logging("worker")
log = logging.getLogger("worker")


async def run_execution(exec_id: str) -> None:
    maker, eid = session_maker(), uuid.UUID(exec_id)
    CTX["execution_id"].set(exec_id)
    async with maker() as db:
        e = await db.get(Execution, eid)
        if not e or e.status != "PENDING":
            return
        org_id, project_id, user_id, mission, workflow = e.organization_id, e.project_id, e.created_by, e.mission, e.workflow
        CTX["organization_id"].set(str(org_id))
        e.status, e.started_at = "RUNNING", datetime.now(timezone.utc)
        await db.commit()
        agents = (await db.execute(select(Agent).where(Agent.organization_id == org_id,
                                                       Agent.deleted_at.is_(None)))).scalars().all()
        overrides = {a.role: {"model": a.model, "system_prompt": a.system_prompt, "temperature": a.temperature}
                     for a in agents}
        project_mem = [m.content for m in await DBMemoryStore(db, org_id).recall("project", str(project_id), mission, 4)]
        provider_rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.organization_id == org_id,
                                                                      ProviderConfig.enabled.is_(True)))).scalars().all()
        ai_settings = (await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))).scalar_one_or_none()
        box = get_secretbox() if any(p.api_key_enc for p in provider_rows) else None
        provider_cfgs = [ProviderCfg(p.kind, p.name, p.base_url,
                                     box.decrypt(p.api_key_enc, aad=str(org_id)) if p.api_key_enc else None,
                                     p.models, True, p.priority, p.local) for p in provider_rows]

    seq = 0
    task_ids: dict[str, uuid.UUID] = {}
    model = get_settings().default_model
    runtime = None  # fournisseurs configurés de l'organisation ; None → configuration d'environnement historique

    async def handle(s, kind: str, d: dict) -> None:
        """Effets de bord persistants d'un événement (même session que l'événement)."""
        if kind == "graph":
            for n in d["nodes"]:
                t = Task(organization_id=org_id, execution_id=eid, key=n["id"], title=n["title"], agent=n["agent"])
                s.add(t); await s.flush(); task_ids[n["id"]] = t.id
            for n in d["nodes"]:
                for dep in n["depends_on"]:
                    s.add(TaskDependency(task_id=task_ids[n["id"]], depends_on_id=task_ids[dep]))
        elif kind.startswith("task.") and d.get("id") in task_ids and "status" in d:
            t = await s.get(Task, task_ids[d["id"]])
            t.status, t.tokens, t.duration_ms, t.error = d["status"], d["tokens"], d["duration_ms"], d.get("error")
            if kind == "task.completed":
                used = d.get("model") or model  # modèle réellement utilisé (après fallback éventuel)
                price = runtime.registry.get(used) if runtime else None
                t_in, t_out = d.get("tokens_in", 0), d.get("tokens_out", 0)
                s.add(UsageRecord(organization_id=org_id, execution_id=eid, agent=d["agent"], model=used,
                                  tokens=d["tokens"], duration_ms=d["duration_ms"], tokens_in=t_in, tokens_out=t_out,
                                  cost_usd=cost_usd(t_in, t_out, price.cost_in, price.cost_out) if price else 0.0))
        elif kind == "agent.message":
            s.add(AgentMessage(organization_id=org_id, execution_id=eid, sender=d["sender"],
                               recipient=d["recipient"], content=d["content"]))
        elif kind == "task.output":
            t = await s.get(Task, task_ids[d["id"]])
            t.output = d["output"]
        if kind == "task.output" and d["agent"] == "coder":
            files, rejected = parse_file_blocks(d["output"])
            for path, body in files.items():
                f, old = await write_file(s, org_id, user_id, project_id, path, body.encode())
                await _event(s, "file.written", {"path": path, "file_id": str(f.id), "diff": make_diff(old, body, path)[:20000]})
            for r in rejected:
                await _event(s, "file.rejected", {"path": r})
            if get_settings().sandbox_enabled and "main.py" in files:  # exécution isolée (Docker requis)
                try:
                    res = await run_code("python", files["main.py"])
                    await _event(s, "sandbox.result", {"exit_code": res.exit_code, "timed_out": res.timed_out,
                                                       "stdout": res.stdout[:4000], "stderr": res.stderr[:4000]})
                except SandboxUnavailable as ex:
                    await _event(s, "sandbox.unavailable", {"reason": str(ex)})

    async def _event(s, kind: str, data: dict) -> None:
        nonlocal seq
        seq += 1
        s.add(ExecutionEvent(execution_id=eid, seq=seq, kind=kind, data=data))

    async def emit(kind: str, data: dict) -> None:
        async with maker() as s:
            try:
                await handle(s, kind, data)
            except Exception:  # noqa: BLE001 — un effet de bord raté ne doit pas tuer l'exécution
                log.exception("effet de bord de l'événement %s en échec", kind)
                await s.rollback()
            stored = {k: v for k, v in data.items() if k != "output"}  # les sorties vivent dans les tâches/fichiers
            await _event(s, kind, stored)
            await s.commit()

    async def cancelled() -> bool:
        async with maker() as s:
            return (await s.get(Execution, eid)).status == "CANCELLING"

    status, result, error, tokens = "COMPLETED", None, None, 0
    try:
        async with maker() as s:
            await ensure_provider_enabled(s)
        runtime = build_runtime(provider_cfgs, prefs_from_settings(ai_settings), emit)
        if runtime is None:
            provider = get_provider()  # aucun fournisseur configuré dans l'interface : configuration d'environnement
        else:  # routage par rôle selon les préférences ; repli automatique entre fournisseurs
            provider = runtime.provider
            keys = {}
            for role, ov in overrides.items():
                ov["model"] = keys[role] = runtime.route_key(role, ov["model"])
            model = runtime.route_key("planner")
            await emit("model.routing", {"default": model, "roles": keys, "mode": runtime.prefs.mode})
        orch = Orchestrator(provider, model, emit, cancelled, agent_overrides=overrides)
        mission_ctx = mission + ("\n\nMémoire du projet:\n" + "\n".join(project_mem) if project_mem else "")
        preset = graph_from_workflow(workflow) if workflow else None
        out = await orch.run(mission_ctx, preset)
        result, tokens = out["output"], out["tokens"]
    except ExecutionCancelled:
        status = "CANCELLED"
    except Exception as ex:  # noqa: BLE001
        status, error = "FAILED", str(ex)
        log.exception("exécution en échec")
        await emit("execution.failed", {"error": error})

    async with maker() as s:
        e = await s.get(Execution, eid)
        e.status, e.result, e.error, e.tokens, e.finished_at = status, result, error, tokens, func.now()
        if result:
            await DBMemoryStore(s, org_id).add("project", str(project_id), f"Mission: {mission[:300]}\nRésultat: {result[:3000]}")
        s.add(Notification(user_id=user_id, organization_id=org_id, title=f"Exécution {status.lower()}",
                           body=mission[:140]))
        await s.commit()


async def main() -> None:
    r = client()
    log.info("en attente de jobs sur %s", QUEUE)
    while True:
        item = await r.blpop(QUEUE, timeout=5)
        if item:
            try:
                await run_execution(item[1])
            except Exception:  # noqa: BLE001 — le worker survit à un job défaillant
                log.exception("job abandonné")


if __name__ == "__main__":
    asyncio.run(main())
