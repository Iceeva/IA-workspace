"""Orchestrateur : plan → graphe → exécution parallèle par couches → test/debug → review."""
from __future__ import annotations
import asyncio
import json
import re
from typing import Awaitable, Callable

from app.agents.base import BaseAgent
from app.agents.roles import ROLES, build_agent
from app.llm.base import LLMProvider
from .graph import GraphError, TaskGraph, TaskNode, TaskStatus

EventSink = Callable[[str, dict], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]

DEFAULT_PLAN = [
    TaskNode("research", "Analyse du besoin", "researcher"),
    TaskNode("architecture", "Architecture", "architect", ["research"]),
    TaskNode("code", "Implémentation", "coder", ["architecture"]),
    TaskNode("test", "Tests", "tester", ["code"]),
    TaskNode("review", "Revue finale", "reviewer", ["test"]),
]


class ExecutionCancelled(Exception):
    pass


def graph_from_workflow(nodes: list[dict], known: Callable[[str], bool] | None = None) -> TaskGraph:
    """Construit et valide un graphe fourni par l'utilisateur (éditeur de workflows)."""
    if not nodes:
        raise GraphError("Le workflow est vide")
    out = []
    for n in nodes:
        agent = str(n.get("agent", ""))
        if not _allowed(agent, known):
            raise GraphError(f"Agent non autorisé dans un workflow: {agent}")
        out.append(TaskNode(str(n["id"]), str(n.get("title") or agent.capitalize()), agent,
                            [str(d) for d in n.get("depends_on", [])]))
    return TaskGraph(out)


def _allowed(agent: str, known: Callable[[str], bool] | None) -> bool:
    """Rôles standard (hors planner/debugger, internes) ou agent du catalogue accepté par `known`."""
    if agent in ROLES:
        return agent not in ("planner", "debugger")
    return bool(known and known(agent))


def parse_plan(raw: str, known: Callable[[str], bool] | None = None) -> TaskGraph:
    """Extrait le JSON du Planner ; valide agents et dépendances."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise GraphError("Le plan ne contient pas de JSON")
    try:
        data = json.loads(m.group(0))
        nodes = [TaskNode(str(t["id"]), str(t["title"]), str(t["agent"]), [str(d) for d in t.get("depends_on", [])])
                 for t in data["tasks"]]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise GraphError(f"Plan invalide: {e}") from e
    for n in nodes:
        if not _allowed(n.agent, known):
            raise GraphError(f"Agent non autorisé dans un plan: {n.agent}")
    if not nodes:
        raise GraphError("Le plan est vide")
    return TaskGraph(nodes)


class Orchestrator:
    def __init__(self, provider: LLMProvider, model: str, emit: EventSink,
                 is_cancelled: CancelCheck | None = None, max_fix_rounds: int = 2,
                 agent_overrides: dict[str, dict] | None = None, selector=None, resolve_agent=None,
                 route_for=None, toolbox_for=None):
        """selector : AgentSelector (choisit la short-list du catalogue) ; resolve_agent(id) → AgentDef ;
        route_for(AgentDef) → clé de modèle ; toolbox_for(AgentDef) → ToolBox | None (outils de CET agent)."""
        self.selector, self.resolve_agent, self.route_for, self.toolbox_for = selector, resolve_agent, route_for, toolbox_for
        self.pool: dict[str, object] = {}
        self.provider, self.model, self.emit = provider, model, emit
        self.is_cancelled = is_cancelled or (lambda: asyncio.sleep(0, result=False))
        self.max_fix_rounds = max_fix_rounds
        self.overrides = agent_overrides or {}
        self.total_tokens = 0

    def _catalog_agent(self, role: str):
        return self.resolve_agent(role) if self.resolve_agent and role not in ROLES else None

    def _agent(self, role: str) -> BaseAgent:
        o = self.overrides.get(role, {})
        d = self._catalog_agent(role)
        if d is not None:
            model = o.get("model") or (self.route_for(d) if self.route_for else self.model)
            return BaseAgent(name=d.name, role=d.id, description=d.description, model=model, provider=self.provider,
                             system_prompt=o.get("system_prompt") or d.system_prompt or f"Tu es {d.name}.",
                             temperature=o.get("temperature", 0.2), tools=[t for t, _ in d.tools],
                             toolbox=self.toolbox_for(d) if self.toolbox_for else None)
        return build_agent(role, self.provider, o.get("model", self.model),
                           system_prompt=o.get("system_prompt"), temperature=o.get("temperature"))

    async def plan(self, mission: str) -> TaskGraph:
        agent = self._agent("planner")
        await self.emit("plan.started", {"agent": "planner"})
        note = ""
        if self.pool:
            note = ("\n\nAgents spécialisés disponibles (utilisables dans « agent », en plus des rôles standard) :\n" +
                    "\n".join(f"- {a.id} : {a.description[:140]}" for a in self.pool.values()))
        try:
            res = await agent.run("Mission à décomposer :" + note, mission)
            self.total_tokens += res.tokens
            graph = parse_plan(res.output, lambda a: a in self.pool)
            await self.emit("plan.created", {"source": "planner", "tasks": len(graph.nodes)})
        except GraphError as e:  # repli explicite, journalisé — jamais silencieux
            await self.emit("plan.fallback", {"reason": str(e)})
            graph = TaskGraph([TaskNode(n.id, n.title, n.agent, list(n.depends_on)) for n in DEFAULT_PLAN])
        return graph

    async def run(self, mission: str, preset: TaskGraph | None = None) -> dict:
        if self.selector and not preset:
            sel = self.selector.select(mission)
            self.pool = {a.id: a for a in sel.agents}
            await self.emit("agents.selected", {
                "agents": [{"id": p.agent.id, "name": p.agent.name, "score": p.score, "reason": p.reason}
                           for p in sel.picks], "considered": sel.considered, "catalog_size": sel.catalog_size})
        graph = preset or await self.plan(mission)
        if preset:
            await self.emit("plan.created", {"source": "workflow", "tasks": len(graph.nodes)})
        await self.emit("graph", {"nodes": [self._dump(n) for n in graph.nodes.values()]})
        for layer in graph.layers():
            if await self.is_cancelled():
                self._cancel_rest(graph)
                raise ExecutionCancelled()
            await asyncio.gather(*(self._run_node(n, graph, mission) for n in layer))
            failed = [n for n in layer if n.status is TaskStatus.FAILED]
            if failed:
                self._cancel_rest(graph)
                raise RuntimeError(f"Tâche en échec: {failed[0].title}: {failed[0].error}")
        final = self._final_output(graph)
        await self.emit("execution.completed", {"tokens": self.total_tokens})
        return {"output": final, "tokens": self.total_tokens,
                "tasks": [self._dump(n) for n in graph.nodes.values()]}

    async def _run_node(self, node: TaskNode, graph: TaskGraph, mission: str) -> None:
        node.status = TaskStatus.RUNNING
        await self.emit("task.started", self._dump(node))
        try:
            agent = self._agent(node.agent)
            ctx = f"Mission: {mission}\n\n{graph.upstream_outputs(node)}"
            res = await agent.run(node.title, ctx)
            node.output, node.tokens, node.duration_ms = res.output, res.tokens, res.duration_ms
            node.tokens_in, node.tokens_out, node.model = res.tokens_in, res.tokens_out, res.model
            self.total_tokens += res.tokens
            if self._is_tester(node.agent):
                await self._test_fix_loop(node, graph, mission, ctx)
            if node.status is TaskStatus.RUNNING:  # ne pas écraser REVIEW_REQUIRED posé par la boucle test/debug
                node.status = TaskStatus.COMPLETED
                await self.emit("task.completed", self._dump(node))
            await self.emit("task.output", {"id": node.id, "agent": node.agent, "output": node.output[:50_000]})
            for other in graph.nodes.values():  # bus de messages : résultat transmis aux agents dépendants
                if node.id in other.depends_on:
                    await self.emit("agent.message", {"sender": node.agent, "recipient": other.agent,
                                                      "content": node.output[:4000]})
        except Exception as e:  # noqa: BLE001 — l'erreur est remontée via l'événement
            node.status, node.error = TaskStatus.FAILED, str(e)
            await self.emit("task.failed", self._dump(node))

    def _is_tester(self, role: str) -> bool:
        d = self._catalog_agent(role)
        return role == "tester" or (d is not None and (d.role_kind == "test" or d.id == "testing-engineer"))

    @staticmethod
    def _add_usage(node: TaskNode, res) -> None:
        """Les tours correctif/re-test sont facturés à la tâche de test (usage et coût fidèles)."""
        node.tokens += res.tokens
        node.tokens_in += res.tokens_in
        node.tokens_out += res.tokens_out

    async def _test_fix_loop(self, node: TaskNode, graph: TaskGraph, mission: str, ctx: str) -> None:
        for round_ in range(1, self.max_fix_rounds + 1):
            if self._verdict(node.output) != "FAIL":
                return
            await self.emit("task.debugging", {"id": node.id, "round": round_})
            fix = await self._agent("debugger").run("Corrige les erreurs signalées.", f"{ctx}\n\n{node.output}")
            self.total_tokens += fix.tokens
            self._add_usage(node, fix)
            retest = await self._agent(node.agent).run(node.title, f"{ctx}\n\nCorrectif:\n{fix.output}")
            self.total_tokens += retest.tokens
            self._add_usage(node, retest)
            node.output = f"{retest.output}\n\n--- correctif (tour {round_}) ---\n{fix.output}"
        if self._verdict(node.output.split("--- correctif")[0]) == "FAIL":
            node.status = TaskStatus.REVIEW_REQUIRED
            await self.emit("task.review_required", self._dump(node))

    @staticmethod
    def _verdict(text: str) -> str:
        hits = re.findall(r"VERDICT:\s*(PASS|FAIL)", text, re.I)
        return hits[-1].upper() if hits else "PASS"

    @staticmethod
    def _cancel_rest(graph: TaskGraph) -> None:
        for n in graph.nodes.values():
            if n.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
                n.status = TaskStatus.CANCELLED

    @staticmethod
    def _final_output(graph: TaskGraph) -> str:
        sinks = {i for i in graph.nodes} - {d for n in graph.nodes.values() for d in n.depends_on}
        return "\n\n".join(graph.nodes[i].output for i in sorted(sinks))

    @staticmethod
    def _dump(n: TaskNode) -> dict:
        return {"id": n.id, "title": n.title, "agent": n.agent, "depends_on": n.depends_on,
                "status": n.status.value, "tokens": n.tokens, "duration_ms": n.duration_ms, "error": n.error,
                "tokens_in": n.tokens_in, "tokens_out": n.tokens_out, "model": n.model}
