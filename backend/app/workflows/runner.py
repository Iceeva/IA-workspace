"""Moteur de workflows (§25) : séquences, parallélisme, conditions, boucles, fusion, retries, timeouts, validation
humaine, appels HTTP, exécution de code. Définition JSON validée avant toute exécution."""
from __future__ import annotations
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from . import expr as X

NODE_TYPES = ("agent", "condition", "merge", "human", "http", "code", "loop", "transform")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
MAX_NODES, MAX_LOOP, MAX_TIMEOUT, MAX_RETRIES = 100, 20, 3600, 5
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
LEAF_TYPES = ("agent", "http", "code", "transform")


class WorkflowError(ValueError):
    pass


@dataclass
class Node:
    id: str
    type: str
    title: str
    spec: dict
    depends_on: list[str] = field(default_factory=list)
    when: str | None = None
    retries: int = 0
    timeout_s: float = 300.0
    on_error: str = "fail"
    backoff_s: float = 1.0


def _parse_expr(text, where: str) -> None:
    try:
        X.parse(text)
    except X.ExprError as e:
        raise WorkflowError(f"{where} : expression invalide ({e})") from e


def _validate_leaf(spec: dict, where: str) -> None:
    t = spec.get("type")
    if t == "agent" and not isinstance(spec.get("agent"), str):
        raise WorkflowError(f"{where} : « agent » obligatoire")
    if t == "http":
        if str(spec.get("method", "GET")).upper() not in HTTP_METHODS or not isinstance(spec.get("url"), str):
            raise WorkflowError(f"{where} : méthode HTTP ou url invalide")
    if t == "code" and (spec.get("language") not in ("python",) or not isinstance(spec.get("code"), str)):
        raise WorkflowError(f"{where} : code Python obligatoire (language=python)")
    if t == "transform" and not isinstance(spec.get("value"), str):
        raise WorkflowError(f"{where} : « value » obligatoire")


def validate_definition(defn: dict) -> list[Node]:
    nodes_raw = defn.get("nodes") if isinstance(defn, dict) else None
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise WorkflowError("Le workflow doit contenir au moins un nœud")
    if len(nodes_raw) > MAX_NODES:
        raise WorkflowError(f"Maximum {MAX_NODES} nœuds")
    nodes: dict[str, Node] = {}
    for r in nodes_raw:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not ID_RE.match(r["id"]):
            raise WorkflowError("Identifiant de nœud invalide (lettre puis lettres/chiffres/_ , 40 max)")
        if r["id"] in nodes or r["id"] in ("trigger", "iteration", "last"):
            raise WorkflowError(f"Identifiant dupliqué ou réservé : {r['id']}")
        t = r.get("type")
        if t not in NODE_TYPES:
            raise WorkflowError(f"Type de nœud inconnu : {t}")
        w = f"nœud {r['id']}"
        if t in LEAF_TYPES:
            _validate_leaf(r, w)
        if t == "condition":
            _parse_expr(r.get("expr", ""), w)
        if t == "human" and not isinstance(r.get("message"), str):
            raise WorkflowError(f"{w} : « message » obligatoire")
        if t == "loop":
            body = r.get("body")
            if not isinstance(body, dict) or body.get("type") not in LEAF_TYPES:
                raise WorkflowError(f"{w} : « body » doit être un nœud agent/http/code/transform")
            _validate_leaf(body, w + " (body)")
            _parse_expr(r.get("until", ""), w)
            if not (1 <= int(r.get("max_iterations", 0) or 0) <= MAX_LOOP):
                raise WorkflowError(f"{w} : max_iterations entre 1 et {MAX_LOOP}")
        if r.get("when") is not None:
            _parse_expr(r["when"], w)
        retries, timeout = int(r.get("retries", 0)), float(r.get("timeout_s", 3600 if t == "human" else 300))
        if not (0 <= retries <= MAX_RETRIES) or not (0 < timeout <= MAX_TIMEOUT):
            raise WorkflowError(f"{w} : retries 0-{MAX_RETRIES}, 0 < timeout_s ≤ {MAX_TIMEOUT}")
        if r.get("on_error", "fail") not in ("fail", "continue"):
            raise WorkflowError(f"{w} : on_error = fail | continue")
        nodes[r["id"]] = Node(r["id"], t, str(r.get("title") or r["id"]), r, [str(d) for d in r.get("depends_on", [])],
                              r.get("when"), retries, timeout, r.get("on_error", "fail"), float(r.get("backoff_s", 1)))
    for n in nodes.values():
        for d in n.depends_on:
            if d not in nodes:
                raise WorkflowError(f"« {n.id} » dépend de « {d} » qui n'existe pas")
    _layers(nodes)
    return list(nodes.values())


def _layers(nodes: dict[str, Node]) -> list[list[Node]]:
    remaining, done, out = dict(nodes), set(), []
    while remaining:
        layer = [n for n in remaining.values() if all(d in done for d in n.depends_on)]
        if not layer:
            raise WorkflowError("Cycle détecté dans le workflow")
        out.append(layer)
        done |= {n.id for n in layer}
        for n in layer:
            del remaining[n.id]
    return out


@dataclass
class NodeState:
    id: str
    type: str
    status: str = "PENDING"        # PENDING RUNNING COMPLETED FAILED SKIPPED CANCELLED WAITING
    output: str = ""
    result: object = None
    error: str | None = None
    attempts: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    tolerated: bool = False        # échec toléré (on_error=continue)

    def dump(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class WorkflowResult:
    status: str
    nodes: dict[str, NodeState]
    output: str
    error: str | None = None

    @property
    def usage(self) -> list[NodeState]:
        return [s for s in self.nodes.values() if s.tokens_in or s.tokens_out]


Emit = Callable[[str, dict], Awaitable[None]]


class WorkflowRunner:
    def __init__(self, definition: dict, *, run_agent=None, http=None, run_code=None, approver=None,
                 emit: Emit | None = None, is_cancelled=None, max_parallel: int = 4, sleep=asyncio.sleep):
        self.nodes = {n.id: n for n in validate_definition(definition)}
        self.layers = _layers(self.nodes)
        self.run_agent, self.http, self.run_code, self.approver = run_agent, http, run_code, approver
        self.emit, self.is_cancelled, self.sleep = emit, is_cancelled, sleep
        self.sem = asyncio.Semaphore(max_parallel)
        self.states = {i: NodeState(i, n.type) for i, n in self.nodes.items()}
        self.trigger: dict = {}

    async def _emit(self, kind: str, st: NodeState) -> None:
        if self.emit:
            await self.emit(kind, st.dump())

    def _ctx(self, extra: dict | None = None) -> dict:
        ctx = {"trigger": self.trigger}
        for i, s in self.states.items():
            ctx[i] = {"output": s.output, "status": s.status, "result": s.result}
        return {**ctx, **(extra or {})}

    def _upstream_text(self, n: Node) -> str:
        parts = [f"[{d}] {self.states[d].output}" for d in n.depends_on if self.states[d].status == "COMPLETED"]
        trig = json.dumps(self.trigger, ensure_ascii=False)[:4000] if self.trigger else ""
        return (f"Déclencheur : {trig}\n\n" if trig else "") + "\n\n".join(parts)

    async def run(self, trigger_payload: dict | None = None) -> WorkflowResult:
        self.trigger = trigger_payload or {}
        status, error = "COMPLETED", None
        for layer in self.layers:
            if self.is_cancelled and await self.is_cancelled():
                status = "CANCELLED"
                break
            await asyncio.gather(*(self._run_node(n) for n in layer))
            hard = [self.states[n.id] for n in layer if self.states[n.id].status == "FAILED" and not self.states[n.id].tolerated]
            if hard:
                status, error = "FAILED", f"{hard[0].id} : {hard[0].error}"
                break
        if status != "COMPLETED":
            for s in self.states.values():
                if s.status in ("PENDING", "WAITING"):
                    s.status = "CANCELLED"
        return WorkflowResult(status, self.states, self._final_output(), error)

    def _final_output(self) -> str:
        has_child = {d for n in self.nodes.values() for d in n.depends_on}
        sinks = [s for i, s in self.states.items() if i not in has_child and s.status == "COMPLETED"]
        return "\n\n".join(s.output for s in sinks)

    async def _run_node(self, n: Node) -> None:
        st = self.states[n.id]
        deps = [self.states[d] for d in n.depends_on]
        usable = [d for d in deps if d.status == "COMPLETED" or (d.status == "FAILED" and d.tolerated)]
        if (n.type == "merge" and deps and not any(d.status == "COMPLETED" for d in deps)) or \
           (n.type != "merge" and len(usable) != len(deps)):
            st.status, st.error = "SKIPPED", "dépendance non satisfaite"
            return await self._emit("workflow.node.skipped", st)
        try:
            if n.when and not X.truthy(n.when, self._ctx()):
                st.status, st.error = "SKIPPED", "condition « when » fausse"
                return await self._emit("workflow.node.skipped", st)
        except X.ExprError as e:
            st.status, st.error = "FAILED", f"when : {e}"
            return await self._emit("workflow.node.failed", st)
        async with self.sem:
            st.status = "RUNNING"
            await self._emit("workflow.node.started", st)
            t0 = time.monotonic()
            for attempt in range(1, n.retries + 2):
                st.attempts = attempt
                try:
                    await asyncio.wait_for(self._execute(n, st), n.timeout_s)
                    st.status, st.error = "COMPLETED", None
                    break
                except asyncio.TimeoutError:
                    st.error = f"délai dépassé ({n.timeout_s:g}s)"
                except Exception as e:  # noqa: BLE001 — l'erreur du nœud est portée par son état
                    st.error = f"{type(e).__name__}: {e}"[:500]
                    if isinstance(e, (WorkflowError, X.ExprError, PermissionError)):
                        break  # inutile de réessayer une erreur de définition ou un refus
                if attempt <= n.retries:
                    await self._emit("workflow.node.retry", st)
                    await self.sleep(n.backoff_s * 2 ** (attempt - 1))
            if st.status != "COMPLETED":
                st.status = "FAILED"
                st.tolerated = n.on_error == "continue"
            st.duration_ms = int((time.monotonic() - t0) * 1000)
        await self._emit("workflow.node.completed" if st.status == "COMPLETED" else "workflow.node.failed", st)

    # -- exécution par type ------------------------------------------------------------------------------------
    async def _execute(self, n: Node, st: NodeState) -> None:
        ctx = self._ctx()
        if n.type == "condition":
            v = X.truthy(n.spec["expr"], ctx)
            st.output, st.result = ("true" if v else "false"), v
        elif n.type == "merge":
            st.output = "\n\n".join(self.states[d].output for d in n.depends_on if self.states[d].status == "COMPLETED")
        elif n.type == "human":
            if self.approver is None:
                raise PermissionError("Aucun circuit de validation humaine configuré")
            st.status = "WAITING"
            await self._emit("workflow.node.waiting", st)
            from app.tools.registry import ApprovalRequest
            ok = await self.approver.request(ApprovalRequest("workflow", n.id, X.render(n.spec["message"], ctx)[:500]))
            st.status = "RUNNING"
            if not ok:
                raise PermissionError("Validation humaine refusée")
            st.output, st.result = "approved", True
        elif n.type == "loop":
            outs = []
            for i in range(1, int(n.spec["max_iterations"]) + 1):
                sub = NodeState(n.id, n.spec["body"]["type"])
                await self._leaf(n.spec["body"], n, sub, {"iteration": i})
                self._acc(st, sub)
                outs.append(sub.output)
                st.output = sub.output
                if X.truthy(n.spec["until"], self._ctx({"iteration": i, "last": {"output": sub.output, "result": sub.result}})):
                    break
            st.result = {"iterations": len(outs), "outputs": outs}
        else:
            await self._leaf(n.spec, n, st, {})

    @staticmethod
    def _acc(st: NodeState, sub: NodeState) -> None:
        st.tokens_in += sub.tokens_in; st.tokens_out += sub.tokens_out; st.model = sub.model or st.model

    async def _leaf(self, spec: dict, n: Node, st: NodeState, extra: dict) -> None:
        ctx = self._ctx(extra)
        t = spec["type"]
        if t == "transform":
            st.output = X.render(spec["value"], ctx)
        elif t == "agent":
            if self.run_agent is None:
                raise WorkflowError("Aucun exécuteur d'agents configuré")
            instruction = X.render(spec.get("instruction") or n.title, ctx)
            r = await self.run_agent(spec["agent"], instruction, self._upstream_text(n))
            st.output = r.output
            st.tokens_in += getattr(r, "tokens_in", 0); st.tokens_out += getattr(r, "tokens_out", 0)
            st.model = getattr(r, "model", "") or st.model
        elif t == "http":
            if self.http is None:
                raise WorkflowError("Aucun client HTTP configuré")
            body = spec.get("body")
            body_s = X.render(body, ctx) if isinstance(body, str) else (json.dumps(
                {k: X.render(v, ctx) if isinstance(v, str) else v for k, v in body.items()}) if isinstance(body, dict) else None)
            headers = {k: X.render(str(v), ctx) for k, v in (spec.get("headers") or {}).items()}
            code, text = await self.http(str(spec.get("method", "GET")).upper(), X.render(spec["url"], ctx), headers, body_s)
            st.output, st.result = text, {"status": code}
            if code >= 400:
                raise RuntimeError(f"HTTP {code}")
        elif t == "code":
            if self.run_code is None:
                raise WorkflowError("Aucune sandbox d'exécution configurée")
            r = await self.run_code("python", X.render(spec["code"], ctx))
            st.output, st.result = r.stdout, {"exit_code": r.exit_code, "stderr": r.stderr}
            if r.timed_out or r.exit_code != 0:
                raise RuntimeError(f"code : sortie {r.exit_code}{' (délai)' if r.timed_out else ''} {r.stderr[:200]}")
