import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from app.tools.registry import CallbackApprover
from app.workflows import expr as X
from app.workflows import triggers as T
from app.workflows.http import safe_http
from app.workflows.runner import WorkflowError, WorkflowRunner, validate_definition


def run(c): return asyncio.run(c)


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    raise AssertionError(f"{exc.__name__} non levée")


# -- expressions ------------------------------------------------------------------------------------------------
CTX = {"a": {"output": "VERDICT: PASS ok", "status": "COMPLETED", "result": 3}, "trigger": {"branch": "main", "n": 7}}


def test_expressions_evaluate_safely():
    assert X.truthy("'PASS' in a.output and a.result >= 3", CTX)
    assert X.truthy("trigger.branch == 'main' and not (trigger.n < 5)", CTX)
    assert X.evaluate("len(a.output) + 1", CTX) == 17 and X.evaluate("a.output.lower().startswith('verdict')", CTX)
    assert X.evaluate("'x' if a.result > 5 else 'y'", CTX) == "y" and X.evaluate("trigger['n'] // 2", CTX) == 3


def test_expressions_block_escapes_and_abuse():
    for bad in ("__import__('os')", "a.__class__", "open('f')", "a.output.format()", "[x for x in a]", "lambda: 1",
                "a.output.join", "(lambda x: x)(1)", "eval('1')", "a.output * 99999999", "_x", "x = 1", "a.output.__len__()"):
        raises(lambda b=bad: X.evaluate(b, CTX), X.ExprError)
    raises(lambda: X.evaluate("zzz", CTX), X.ExprError)
    raises(lambda: X.evaluate("a.nofield", CTX), X.ExprError)
    raises(lambda: X.parse("1" + "+1" * 400), X.ExprError)
    raises(lambda: X.evaluate("1/0", {}), X.ExprError)


def test_templates():
    assert X.render("Branche {{trigger.branch}} / {{ a.status }}", CTX) == "Branche main / COMPLETED"
    raises(lambda: X.render("{{ inconnue.x }}", CTX), X.ExprError)
    assert X.render("pas de variable", CTX) == "pas de variable"


# -- cron ---------------------------------------------------------------------------------------------------------
def dt(*a): return datetime(*a, tzinfo=timezone.utc)


def test_cron_next_run_cases():
    assert T.next_run("*/15 * * * *", dt(2026, 10, 8, 10, 7)) == dt(2026, 10, 8, 10, 15)
    assert T.next_run("0 9 * * *", dt(2026, 10, 8, 9, 0)) == dt(2026, 10, 9, 9, 0)          # strictement après
    assert T.next_run("30 2 1 * *", dt(2026, 10, 8, 0, 0)) == dt(2026, 11, 1, 2, 30)
    assert T.next_run("0 8 * * mon", dt(2026, 10, 8, 0, 0)) == dt(2026, 10, 12, 8, 0)      # 8 oct 2026 = jeudi
    assert T.next_run("0 0 29 2 *", dt(2026, 3, 1, 0, 0)) == dt(2028, 2, 29, 0, 0)
    assert T.next_run("0 12 15 * 5", dt(2026, 10, 8, 0, 0)) == dt(2026, 10, 9, 12, 0)       # jour du mois OU jour de semaine
    assert T.next_run("0 0 * * 7", dt(2026, 10, 8, 0, 0)) == dt(2026, 10, 11, 0, 0)         # 7 = dimanche
    assert T.next_run("5,35 */6 * 1-3 *", dt(2026, 12, 31, 23, 59)) == dt(2027, 1, 1, 0, 5)


def test_cron_rejects_bad_expressions():
    for bad in ("* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a b c d e", "5-1 * * * *", "* * 32 * *"):
        raises(lambda b=bad: T.parse_cron(b), T.CronError)
    raises(lambda: T.next_run("0 0 31 2 *", dt(2026, 1, 1, 0, 0)), T.CronError)


# -- webhooks et événements -----------------------------------------------------------------------------------------
def test_webhook_signature_replay_and_tamper():
    body = b'{"x":1}'
    ts, sig = T.sign_webhook("s3cret", body, 1_000_000)
    assert T.verify_webhook("s3cret", body, ts, sig, now=1_000_100)
    assert not T.verify_webhook("s3cret", body, ts, sig, now=1_000_000 + 301)                 # rejeu
    assert not T.verify_webhook("s3cret", b'{"x":2}', ts, sig, now=1_000_100)                 # corps modifié
    assert not T.verify_webhook("autre", body, ts, sig, now=1_000_100)
    assert not T.verify_webhook("s3cret", body, None, sig) and not T.verify_webhook("s3cret", body, "abc", sig)


def test_github_signature():
    import hashlib, hmac
    body = b'{"ref":"refs/heads/main"}'
    good = "sha256=" + hmac.new(b"k", body, hashlib.sha256).hexdigest()
    assert T.verify_github("k", body, good) and not T.verify_github("k", body + b" ", good)
    assert not T.verify_github("k", body, None) and not T.verify_github("k", body, "sha1=abc")


def test_event_matching_with_globs_and_lists():
    ev = {"type": "github", "event": "push", "repo": "acme/api", "branch": "release/1.2"}
    assert T.matches("github", {"filter": {"event": "push", "branch": "release/*"}}, ev)
    assert T.matches("github", {"filter": {"repo": ["acme/web", "acme/api"]}}, ev) and T.matches("github", {}, ev)
    assert not T.matches("github", {"filter": {"branch": "main"}}, ev) and not T.matches("db_event", {}, ev)
    assert not T.matches("github", {"filter": {"missing": "x"}}, ev)
    assert T.matches("file_added", {"filter": {"path": "docs/*.pdf"}}, {"type": "file_added", "path": "docs/a.pdf"})


# -- validation du moteur ---------------------------------------------------------------------------------------------
def test_definition_validation():
    ok = {"nodes": [{"id": "a", "type": "transform", "value": "x"}, {"id": "b", "type": "merge", "depends_on": ["a"]}]}
    assert [n.id for n in validate_definition(ok)] == ["a", "b"]
    bad = [
        {}, {"nodes": []}, {"nodes": [{"id": "1a", "type": "merge"}]}, {"nodes": [{"id": "trigger", "type": "merge"}]},
        {"nodes": [{"id": "a", "type": "nope"}]}, {"nodes": [{"id": "a", "type": "agent"}]},
        {"nodes": [{"id": "a", "type": "merge", "depends_on": ["zz"]}]},
        {"nodes": [{"id": "a", "type": "merge", "depends_on": ["b"]}, {"id": "b", "type": "merge", "depends_on": ["a"]}]},
        {"nodes": [{"id": "a", "type": "merge"}, {"id": "a", "type": "merge"}]},
        {"nodes": [{"id": "a", "type": "condition", "expr": "__import__('os')"}]},
        {"nodes": [{"id": "a", "type": "merge", "retries": 99}]}, {"nodes": [{"id": "a", "type": "merge", "timeout_s": 0}]},
        {"nodes": [{"id": "a", "type": "http", "method": "TRACE", "url": "https://x"}]},
        {"nodes": [{"id": "a", "type": "code", "language": "bash", "code": "ls"}]},
        {"nodes": [{"id": "a", "type": "loop", "body": {"type": "merge"}, "until": "True", "max_iterations": 2}]},
        {"nodes": [{"id": "a", "type": "loop", "body": {"type": "transform", "value": "x"}, "until": "True", "max_iterations": 99}]},
    ]
    for b in bad:
        raises(lambda b=b: validate_definition(b), WorkflowError)


# -- exécution ------------------------------------------------------------------------------------------------------
class Agents:
    def __init__(self, replies=None, delay=0): self.calls, self.replies, self.delay, self.active, self.peak = [], replies or {}, delay, 0, 0
    async def __call__(self, agent, instruction, context):
        self.active += 1; self.peak = max(self.peak, self.active)
        await asyncio.sleep(self.delay); self.active -= 1
        self.calls.append((agent, instruction, context))
        r = self.replies.get(agent, "ok")
        if isinstance(r, Exception): raise r
        if isinstance(r, list): r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception): raise r
        return NS(output=r, tokens_in=10, tokens_out=5, model="m1")


def runner(defn, **kw):
    kw.setdefault("sleep", lambda s: asyncio.sleep(0))
    return WorkflowRunner(defn, **kw)


def test_parallel_branches_condition_gating_and_merge():
    ag = Agents({"x": "PASS", "y": "yy"}, delay=0.05)
    d = {"nodes": [
        {"id": "a", "type": "agent", "agent": "x", "instruction": "fais {{trigger.what}}"},
        {"id": "b", "type": "agent", "agent": "y"},
        {"id": "c", "type": "condition", "expr": "'PASS' in a.output", "depends_on": ["a", "b"]},
        {"id": "ok", "type": "transform", "value": "gagné {{a.output}}", "depends_on": ["c"], "when": "c.result"},
        {"id": "ko", "type": "transform", "value": "perdu", "depends_on": ["c"], "when": "not c.result"},
        {"id": "m", "type": "merge", "depends_on": ["ok", "ko"]}]}
    res = run(runner(d, run_agent=ag).run({"what": "X"}))
    s = res.nodes
    assert res.status == "COMPLETED" and ag.peak == 2                              # a et b en parallèle
    assert ag.calls[0][1] == "fais X"
    assert (s["ok"].status, s["ko"].status, s["m"].output) == ("COMPLETED", "SKIPPED", "gagné PASS")
    assert res.output == "gagné PASS" and s["a"].tokens_in == 10 and len(res.usage) == 2


def test_retry_with_backoff_then_success_and_exhaustion():
    sleeps = []
    async def sl(s): sleeps.append(s)
    flaky = Agents({"x": [RuntimeError("503"), RuntimeError("503"), "enfin"]})
    d = {"nodes": [{"id": "a", "type": "agent", "agent": "x", "retries": 2, "backoff_s": 1}]}
    res = run(WorkflowRunner(d, run_agent=flaky, sleep=sl).run())
    assert res.status == "COMPLETED" and res.nodes["a"].attempts == 3 and sleeps == [1, 2] and res.nodes["a"].output == "enfin"
    dead = Agents({"x": RuntimeError("down")})
    res = run(WorkflowRunner({"nodes": [{"id": "a", "type": "agent", "agent": "x", "retries": 1},
                                        {"id": "b", "type": "transform", "value": "z", "depends_on": ["a"]}],
                              }, run_agent=dead, sleep=sl).run())
    assert res.status == "FAILED" and "down" in res.error and res.nodes["a"].attempts == 2 and res.nodes["b"].status == "CANCELLED"


def test_timeout_and_tolerated_failure_lets_dependents_run():
    slow = Agents({"x": "late"}, delay=0.3)
    d = {"nodes": [{"id": "a", "type": "agent", "agent": "x", "timeout_s": 0.05, "on_error": "continue"},
                   {"id": "b", "type": "transform", "value": "suite {{a.status}}", "depends_on": ["a"]}]}
    res = run(runner(d, run_agent=slow).run())
    assert res.status == "COMPLETED" and "délai" in res.nodes["a"].error and res.nodes["b"].output == "suite FAILED"


def test_loop_until_condition_and_iteration_cap():
    seq = Agents({"w": ["draft", "draft2", "VERDICT: PASS", "never"]})
    d = {"nodes": [{"id": "l", "type": "loop", "max_iterations": 5, "until": "'PASS' in last.output",
                    "body": {"type": "agent", "agent": "w", "instruction": "tour {{iteration}}"}}]}
    res = run(runner(d, run_agent=seq).run())
    assert res.nodes["l"].result["iterations"] == 3 and res.nodes["l"].output == "VERDICT: PASS"
    assert [c[1] for c in seq.calls] == ["tour 1", "tour 2", "tour 3"] and res.nodes["l"].tokens_in == 30
    cap = run(runner({"nodes": [{"id": "l", "type": "loop", "max_iterations": 2, "until": "False",
                                 "body": {"type": "transform", "value": "i{{iteration}}"}}]}).run())
    assert cap.nodes["l"].result["iterations"] == 2 and cap.nodes["l"].output == "i2"


def test_human_validation_approve_deny_and_missing_circuit():
    d = {"nodes": [{"id": "h", "type": "human", "message": "Déployer {{trigger.v}} ?"},
                   {"id": "go", "type": "transform", "value": "déployé", "depends_on": ["h"]}]}
    asked = []
    async def yes(req): asked.append(req.summary); return True
    res = run(runner(d, approver=CallbackApprover(yes)).run({"v": "1.2"}))
    assert res.status == "COMPLETED" and asked == ["Déployer 1.2 ?"] and res.output == "déployé"
    async def no(req): return False
    res = run(runner(d, approver=CallbackApprover(no)).run({"v": "1"}))
    assert res.status == "FAILED" and res.nodes["go"].status == "CANCELLED" and "refusée" in res.error
    assert run(runner(d).run({"v": "1"})).status == "FAILED"                       # pas de circuit : refus par défaut


def test_http_and_code_nodes_with_injected_executors():
    calls = []
    async def http(method, url, headers, body):
        calls.append((method, url, headers, body)); return 200, '{"ok":true}'
    async def code(lang, src):
        return NS(stdout="42\n", stderr="", exit_code=0, timed_out=False)
    d = {"nodes": [{"id": "h", "type": "http", "method": "post", "url": "https://api.example.com/{{trigger.id}}",
                    "headers": {"X-T": "{{trigger.id}}"}, "body": {"msg": "salut {{trigger.id}}", "n": 1}},
                   {"id": "c", "type": "code", "language": "python", "code": "print(6*7)", "depends_on": ["h"]}]}
    res = run(runner(d, http=http, run_code=code).run({"id": "77"}))
    assert res.status == "COMPLETED" and calls[0][:3] == ("POST", "https://api.example.com/77", {"X-T": "77"})
    assert '"msg": "salut 77"' in calls[0][3] and res.output == "42\n"
    async def bad(method, url, headers, body): return 500, "boom"
    res = run(runner({"nodes": [{"id": "h", "type": "http", "url": "https://x.example"}]}, http=bad).run())
    assert res.status == "FAILED" and "HTTP 500" in res.error
    async def crash(lang, src): return NS(stdout="", stderr="Traceback", exit_code=1, timed_out=False)
    assert run(runner({"nodes": [{"id": "c", "type": "code", "language": "python", "code": "x"}]}, run_code=crash).run()).status == "FAILED"


def test_cancellation_between_layers_and_event_stream():
    n = {"calls": 0}
    async def cancelled():
        n["calls"] += 1; return n["calls"] > 1
    ev = []
    async def emit(k, d): ev.append((k, d["id"]))
    d = {"nodes": [{"id": "a", "type": "transform", "value": "1"}, {"id": "b", "type": "transform", "value": "2", "depends_on": ["a"]}]}
    res = run(runner(d, emit=emit, is_cancelled=cancelled).run())
    assert res.status == "CANCELLED" and res.nodes["a"].status == "COMPLETED" and res.nodes["b"].status == "CANCELLED"
    assert ("workflow.node.started", "a") in ev and ("workflow.node.completed", "a") in ev


def test_failed_when_expression_fails_node_cleanly_and_ssrf_guard():
    res = run(runner({"nodes": [{"id": "a", "type": "transform", "value": "x", "when": "inconnue > 1"}]}).run())
    assert res.status == "FAILED" and "when" in res.error
    for url in ("http://169.254.169.254/latest", "https://localhost/x", "http://example.com"):
        raises(lambda u=url: run(safe_http("GET", u)), ValueError)
