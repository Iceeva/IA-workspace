import asyncio
import json
import pytest

from app.llm.base import LLMProvider, LLMResponse
from app.orchestration.engine import Orchestrator, ExecutionCancelled, parse_plan
from app.orchestration.graph import GraphError, TaskGraph, TaskNode


class Scripted(LLMProvider):
    """Provider de test : réponses pilotées par le rôle présent dans le prompt système."""
    name = "scripted"

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096):
        role = messages[0].content.split()[2].rstrip(".")  # "Tu es <Role>."
        self.calls.append(role)
        queue = self.replies[role]
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return LLMResponse(text, model, 10, 5)


PLAN = json.dumps({"tasks": [
    {"id": "a", "title": "Recherche", "agent": "researcher", "depends_on": []},
    {"id": "b", "title": "Archi", "agent": "architect", "depends_on": []},
    {"id": "c", "title": "Code", "agent": "coder", "depends_on": ["a", "b"]},
    {"id": "d", "title": "Tests", "agent": "tester", "depends_on": ["c"]},
    {"id": "e", "title": "Revue", "agent": "reviewer", "depends_on": ["d"]}]})


def make(replies):
    events = []
    async def emit(kind, data): events.append(kind)
    return Orchestrator(Scripted(replies), "m", emit), events


def test_cycle_detected():
    with pytest.raises(GraphError):
        TaskGraph([TaskNode("a", "A", "coder", ["b"]), TaskNode("b", "B", "coder", ["a"])])


def test_unknown_dependency():
    with pytest.raises(GraphError):
        TaskGraph([TaskNode("a", "A", "coder", ["zzz"])])


def test_diamond_layers():
    g = parse_plan(PLAN)
    assert [sorted(n.id for n in l) for l in g.layers()] == [["a", "b"], ["c"], ["d"], ["e"]]


def test_forbidden_agent_in_plan():
    with pytest.raises(GraphError):
        parse_plan('{"tasks":[{"id":"x","title":"t","agent":"debugger"}]}')


def test_full_run_with_debug_loop():
    orch, events = make({"Planner": [PLAN], "Researcher": ["r"], "Architect": ["ar"], "Coder": ["code"],
                         "Tester": ["VERDICT: FAIL boom", "VERDICT: PASS"], "Debugger": ["fixed"],
                         "Reviewer": ["FINAL"]})
    result = asyncio.run(orch.run("mission"))
    assert "FINAL" in result["output"]
    assert "task.debugging" in events and events[-1] == "execution.completed"
    assert all(t["status"] == "COMPLETED" for t in result["tasks"])


def test_planner_garbage_falls_back_and_is_logged():
    orch, events = make({"Planner": ["pas du json"], "Researcher": ["r"], "Architect": ["a"], "Coder": ["c"],
                         "Tester": ["VERDICT: PASS"], "Reviewer": ["done"]})
    result = asyncio.run(orch.run("m"))
    assert "plan.fallback" in events and len(result["tasks"]) == 5


def test_cancellation():
    events = []
    async def emit(k, d): events.append(k)
    async def cancelled(): return True
    orch = Orchestrator(Scripted({"Planner": [PLAN]}), "m", emit, cancelled)
    with pytest.raises(ExecutionCancelled):
        asyncio.run(orch.run("m"))


def test_workflow_preset_skips_planner():
    from app.orchestration.engine import graph_from_workflow
    wf = [{"id": "a", "agent": "researcher"}, {"id": "b", "agent": "coder", "depends_on": ["a"]},
          {"id": "c", "agent": "reviewer", "depends_on": ["b"]}]
    orch, events = make({"Researcher": ["r"], "Coder": ["c"], "Reviewer": ["done"]})
    result = asyncio.run(orch.run("m", graph_from_workflow(wf)))
    assert "Planner" not in orch.provider.calls and result["output"] == "done"
    with pytest.raises(GraphError):
        graph_from_workflow([{"id": "x", "agent": "debugger"}])
    with pytest.raises(GraphError):
        graph_from_workflow([{"id": "a", "agent": "coder", "depends_on": ["a"]}])


def test_unresolved_failure_keeps_review_required():
    """Si le Tester échoue encore après les tours de correction, la tâche doit rester « À relire »."""
    orch, events = make({"Planner": [PLAN], "Researcher": ["r"], "Architect": ["ar"], "Coder": ["code"],
                         "Tester": ["VERDICT: FAIL boom"], "Debugger": ["fixed"], "Reviewer": ["FINAL"]})
    result = asyncio.run(orch.run("mission"))
    status = {t["id"]: t["status"] for t in result["tasks"]}
    assert status["d"] == "REVIEW_REQUIRED"
    assert "task.review_required" in events
    assert status["e"] == "COMPLETED"


def test_task_events_carry_model_and_split_tokens_including_fix_rounds():
    orch, _ = make({"Planner": [PLAN], "Researcher": ["r"], "Architect": ["ar"], "Coder": ["code"],
                    "Tester": ["VERDICT: FAIL x", "VERDICT: PASS"], "Debugger": ["fixed"], "Reviewer": ["FINAL"]})
    result = asyncio.run(orch.run("mission"))
    d = next(t for t in result["tasks"] if t["id"] == "d")
    # 1 appel Tester + 1 Debugger + 1 re-test = 3 appels de 10 tokens d'entrée / 5 de sortie
    assert (d["tokens_in"], d["tokens_out"], d["tokens"]) == (30, 15, 45) and d["model"]
