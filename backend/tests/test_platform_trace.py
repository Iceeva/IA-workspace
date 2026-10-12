from app.orchestration.trace import build_trace


def E(*items):
    return [{"seq": i + 1, "kind": k, "data": d} for i, (k, d) in enumerate(items)]


def test_trace_explains_selection_model_tools_and_next_agent():
    ev = E(("agents.selected", {"agents": [{"id": "python-developer", "name": "Python Developer", "score": 0.82, "reason": "compétence python"}],
                                "considered": 12, "catalog_size": 1096}),
           ("plan.created", {"source": "planner", "tasks": 2}),
           ("graph", {"nodes": [{"id": "a", "title": "Écrire", "agent": "python-developer", "depends_on": []},
                                {"id": "b", "title": "Revoir", "agent": "reviewer", "depends_on": ["a"]}]}),
           ("task.started", {"id": "a", "title": "Écrire", "agent": "python-developer"}),
           ("model.fallback", {"used": "anthropic:claude", "failed": ["openai:gpt: HTTP 503"]}),
           ("task.trace", {"id": "a", "agent": "python-developer", "model": "anthropic:claude",
                           "tools": [{"tool": "filesystem", "action": "write", "ok": True, "ms": 12}], "tokens_in": 100, "tokens_out": 50}),
           ("task.completed", {"id": "a", "status": "COMPLETED", "tokens": 150, "duration_ms": 900, "error": None}),
           ("task.output", {"id": "a", "agent": "python-developer", "output": "x" * 5000}),
           ("task.started", {"id": "b", "title": "Revoir", "agent": "reviewer"}),
           ("task.completed", {"id": "b", "status": "COMPLETED", "tokens": 20, "duration_ms": 100}))
    t = build_trace(ev)
    a, b = t["steps"]
    assert [s["id"] for s in t["steps"]] == ["a", "b"] and a["next"] == ["b"] and b["next"] == []
    assert "1096" in a["why"] and "compétence python" in a["why"] and b["why"] == "Rôle standard du plan"
    assert a["model"] == "anthropic:claude" and a["tools"][0]["tool"] == "filesystem" and a["fallbacks"][0]["used"] == "anthropic:claude"
    assert len(a["output"]) == 600 and b["fallbacks"] == []                         # sortie tronquée ; la bascule n'est pas attribuée à b
    assert t["totals"] == {"tokens_in": 100, "tokens_out": 50, "duration_ms": 1000, "tool_calls": 1}


def test_trace_marks_replanned_agent_and_tolerates_partial_journal():
    ev = E(("graph", {"nodes": [{"id": "a", "title": "T", "agent": "coder", "depends_on": []}]}),
           ("plan.replanned", {"added": {"id": "a_ext1", "title": "Sécurité", "agent": "security", "depends_on": ["a"]},
                               "requested_by": "coder", "reason": "besoin d'un audit"}),
           ("task.started", {"id": "a", "title": "T", "agent": "coder"}))      # exécution encore en cours
    t = build_trace(ev)
    ext = next(s for s in t["steps"] if s["id"] == "a_ext1")
    assert "coder" in ext["why"] and t["replans"][0]["agent"] == "security" and ext["status"] == "PENDING"
    assert build_trace([])["steps"] == [] and build_trace([{"kind": "inconnu"}])["totals"]["tool_calls"] == 0


def test_tool_loop_records_calls_without_arguments_or_results():
    import asyncio
    from app.agents.tool_loop import run_with_tools
    from app.llm.base import LLMResponse, Message
    from app.tools.registry import ToolError

    class Prov:
        def __init__(self): self.n = 0
        async def chat(self, messages, **kw):
            self.n += 1
            txt = ('```tool\n{"tool":"fs","action":"read","args":{"path":"secret.txt"}}\n```' if self.n == 1 else
                   '```tool\n{"tool":"fs","action":"boom","args":{}}\n```' if self.n == 2 else "terminé")
            return LLMResponse(txt, "p:m", 10, 5)

    class Box:
        async def call(self, tool, action, **a):
            if action == "boom":
                raise ToolError("échec")
            return "contenu confidentiel"

    class Agent:
        provider, model, temperature, toolbox = Prov(), "m", 0.0, Box()
    r = asyncio.run(run_with_tools(Agent(), [Message("system", "s")], 6))
    assert r.content == "terminé" and [(c["tool"], c["action"], c["ok"]) for c in r.calls] == [("fs", "read", True), ("fs", "boom", False)]
    assert all(set(c) == {"tool", "action", "ok", "ms"} for c in r.calls)      # ni arguments ni résultats
