"""Exécution d'une WorkflowRun par le worker : agents du catalogue, routage, outils, approbations, usage et coût."""
from __future__ import annotations
import logging
import uuid

from sqlalchemy import func

from app.bridge.broker import JobBroker
from app.core.config import get_settings
from app.llm.providers import get_provider
from app.models.entities import Notification, UsageRecord, Workflow, WorkflowRun
from app.orchestration.engine import Orchestrator
from app.services import assembly as A
from app.services.budget import cost_usd
from app.services.runtime_factory import build_runtime, prefs_from_settings
from app.tools.builtin import default_registry
from app.workflows.http import safe_http
from app.workflows.runner import WorkflowRunner

log = logging.getLogger("worker.workflow")


async def run_workflow_job(maker, run_id: uuid.UUID, broker: JobBroker | None = None) -> None:
    async with maker() as s:
        run = await s.get(WorkflowRun, run_id)
        wf = await s.get(Workflow, run.workflow_id)
        org_id, user_id, payload, defn, project_id = run.organization_id, run.created_by, run.payload, wf.definition, wf.project_id
        cfgs, providers, ai = await A.load_providers(s, org_id, user_id, broker)
        catalog = await A.load_catalog(s, org_id)
        embedder = A.make_embedder(ai, providers, org_id)
        wf_name = wf.name

    async def emit(kind: str, data: dict) -> None:  # événements de nœuds : conservés dans node_states à la fin
        log.debug("%s %s", kind, data.get("id"))

    runtime = build_runtime(cfgs, prefs_from_settings(ai), emit)
    status, error, output, states = "COMPLETED", None, None, {}
    try:
        provider = runtime.provider if runtime else get_provider()
        model = runtime.route_key("planner") if runtime else get_settings().default_model

        async def search(query: str, k: int) -> list[dict]:
            async with maker() as s2:
                return await A.rag_search(s2, org_id, query, embedder, k, project_id)

        async def start_workflow(name: str, data: dict) -> str:
            async with maker() as s2:
                from sqlalchemy import select
                target = (await s2.execute(select(Workflow).where(Workflow.organization_id == org_id, Workflow.name == name,
                                                                  Workflow.enabled.is_(True), Workflow.deleted_at.is_(None)))).scalar_one_or_none()
                if target is None:
                    raise ValueError(f"Workflow inconnu : {name}")
                s2.add(WorkflowRun(organization_id=org_id, workflow_id=target.id, created_by=user_id,
                                   trigger_type="automation", payload={"type": "automation", **data}))
                await s2.commit()
            return f"workflow « {name} » mis en file"

        registry = default_registry(".", search_url=get_settings().search_url, github_token=get_settings().github_token,
                                    deploy_hooks=_hooks(), run_workflow=start_workflow, rag_search=search)
        if project_id and user_id:
            registry.register(A.project_files_tool(maker, org_id, user_id, project_id))
        approver = A.DbApprover(maker, org_id, user_id, run_id=run_id, emit=emit)
        orch = Orchestrator(
            provider, model, emit, resolve_agent=catalog.get,
            route_for=(lambda a: runtime.route_key("agent", None, a.sensitive, set(a.needs), agent_id=a.id)) if runtime else None,
            toolbox_for=A.toolbox_factory(registry, approver, emit))

        async def run_agent(agent_id: str, instruction: str, context: str):
            return await orch.agent_for(agent_id).run(instruction, context)

        async def run_code(language: str, code: str):
            from app.services.sandbox import run_code as sandbox
            return await sandbox(language, code)

        async def is_cancelled() -> bool:
            async with maker() as s2:
                return (await s2.get(WorkflowRun, run_id)).status == "CANCELLING"

        runner = WorkflowRunner(defn, run_agent=run_agent, http=safe_http, is_cancelled=is_cancelled,
                                run_code=run_code if get_settings().sandbox_enabled else None, approver=approver)
        result = await runner.run(payload)
        status, error, output = result.status, result.error, result.output
        states = {i: st.dump() for i, st in result.nodes.items()}
    except Exception as ex:  # noqa: BLE001 — la définition ou l'assemblage peut échouer : on le consigne dans la run
        status, error = "FAILED", str(ex)[:1000]
        log.exception("workflow en échec")

    async with maker() as s:
        run = await s.get(WorkflowRun, run_id)
        run.status, run.error, run.output, run.node_states, run.finished_at = status, error, output, states, func.now()
        for st in states.values():
            if st.get("tokens_in") or st.get("tokens_out"):
                price = runtime.registry.get(st.get("model", "")) if runtime else None
                s.add(UsageRecord(organization_id=org_id, agent=f"wf:{st['id']}"[:40], model=(st.get("model") or "")[:120],
                                  tokens=st["tokens_in"] + st["tokens_out"], duration_ms=st.get("duration_ms", 0),
                                  tokens_in=st["tokens_in"], tokens_out=st["tokens_out"],
                                  cost_usd=cost_usd(st["tokens_in"], st["tokens_out"], price.cost_in, price.cost_out) if price else 0.0))
        if user_id:
            s.add(Notification(user_id=user_id, organization_id=org_id, title=f"Workflow {status.lower()}", body=wf_name[:140]))
        await s.commit()


def _hooks() -> dict[str, str]:
    import json
    raw = get_settings().deploy_hooks
    try:
        d = json.loads(raw) if raw else {}
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except ValueError:
        return {}
