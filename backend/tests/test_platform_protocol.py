import asyncio
import json

from app.agents.protocol import MessageLog, MsgType, parse_messages
from app.llm.base import LLMProvider, LLMResponse
from app.orchestration.engine import Orchestrator
from app.orchestration.graph import GraphError, TaskGraph, TaskNode


def run(c): return asyncio.run(c)


def blk(**d): return "```aiw-msg\n" + json.dumps(d) + "\n```"


def test_parse_messages_validates_and_strips():
    text = "Résultat.\n" + blk(type="request_agent", agent="security-auditor", reason="vérifier") + "\n" + \
           blk(type="n_importe_quoi") + "\n```aiw-msg\n{pas du json}\n```\n" + blk(type="done", agent="a b")
    clean, msgs = parse_messages(text, "coder", "t1")
    assert clean == "Résultat." and len(msgs) == 1
    assert msgs[0].type is MsgType.REQUEST_AGENT and msgs[0].recipient == "security-auditor" and msgs[0].ref == "t1"


def test_parse_messages_bounds_count_and_content():
    text = "\n".join(blk(type="result", content="x" * 9000) for _ in range(9))
    _, msgs = parse_messages(text, "a")
    assert len(msgs) == 5 and all(len(m.content) == 4000 for m in msgs)


def test_message_log_reconstructs_chain():
    log = MessageLog()
    _, ms = parse_messages(blk(type="request_agent", agent="reviewer"), "coder", "c")
    for m in ms: log.add(m)
    assert log.delegation_chain() == [("coder", "reviewer")] and log.thread("c")[0]["type"] == "request_agent"
    assert log.between("reviewer", "coder") and not log.between("x", "y")


def test_graph_add_rejects_duplicates_unknown_deps():
    g = TaskGraph([TaskNode("a", "A", "coder")])
    g.add(TaskNode("b", "B", "reviewer", ["a"]))
    for bad in (TaskNode("b", "B", "x"), TaskNode("c", "C", "x", ["zz"])):
        try: g.add(bad); assert False
        except GraphError: pass
    assert list(g.nodes) == ["a", "b"]


class Prov(LLMProvider):
    name = "p"
    def __init__(self, coder_reply): self.coder_reply, self.roles = coder_reply, []
    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096):
        role = messages[0].content.split()[2].rstrip(".")
        self.roles.append(role)
        return LLMResponse(self.coder_reply if role == "Coder" else f"ok {role}", model, 10, 5)


def orch(reply, **kw):
    events = []
    async def emit(k, d): events.append((k, d))
    return Orchestrator(Prov(reply), "m", emit, **kw), events


def graph(): return TaskGraph([TaskNode("code", "Implémentation", "coder")])


def test_replan_adds_requested_agent_and_runs_it():
    o, ev = orch("Code fait.\n" + blk(type="request_agent", agent="reviewer", reason="relire"))
    r = run(o.run("m", preset=graph()))
    kinds = [k for k, _ in ev]
    assert "plan.replanned" in kinds
    assert [t["id"] for t in r["tasks"]] == ["code", "code_ext1"] and all(t["status"] == "COMPLETED" for t in r["tasks"])
    assert "```" not in r["tasks"][0]["id"] and o.log.delegation_chain() == [("coder", "reviewer")]
    assert "aiw-msg" not in r["output"]


def test_replan_refuses_unknown_agent_and_internal_roles():
    for who in ("agent-inexistant", "planner", "debugger"):
        o, ev = orch(blk(type="request_agent", agent=who), max_replans=3)
        r = run(o.run("m", preset=graph()))
        assert len(r["tasks"]) == 1 and any(k == "plan.replan_refused" for k, _ in ev)


def test_replan_is_bounded():
    o, ev = orch(blk(type="request_agent", agent="coder"), max_replans=2)   # chaque coder redemande un coder
    r = run(o.run("m", preset=graph()))
    assert len(r["tasks"]) == 3 and o.replans == 2 and any(k == "plan.replan_refused" for k, _ in ev)
