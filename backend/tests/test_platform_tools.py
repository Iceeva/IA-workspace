import asyncio
import subprocess
import tempfile
from pathlib import Path

from app.catalog.catalog import Catalog
from app.catalog.model import Permission
from app.tools.builtin import default_registry, safe_eval
from app.tools.registry import (ApprovalDenied, CallbackApprover, MemoryApprovalStore, PermissionDenied, ToolBox,
                                ToolError)


def box(root, grants, approver=None, log=None):
    async def audit(k, d): log.append((k, d))
    kw = {"approver": approver} if approver else {}
    return ToolBox(default_registry(root), grants, audit=audit if log is not None else None, agent="t", **kw)


def run(c): return asyncio.run(c)


def test_agent_only_sees_granted_available_tools():
    with tempfile.TemporaryDirectory() as d:
        b = box(d, {"filesystem": Permission.READ, "terminal": Permission.EXECUTE, "git": Permission.NONE})
        assert b.visible_tools() == ["filesystem"]       # terminal : prévu mais non implémenté ; git : NONE


def test_permission_levels_are_enforced_and_audited():
    with tempfile.TemporaryDirectory() as d:
        log = []; b = box(d, {"filesystem": Permission.READ}, log=log)
        try:
            run(b.call("filesystem", "write", path="a.txt", content="x")); assert False
        except PermissionDenied as e:
            assert "WRITE" in str(e) and "READ" in str(e)
        assert log[0][0] == "tool.denied" and not (Path(d) / "a.txt").exists()
        try:
            run(b.call("github", "x")); assert False
        except ToolError as e:
            assert "indisponible" in str(e)
        try:
            run(b.call("filesystem", "nope")); assert False
        except ToolError:
            pass
        try:
            run(b.call("filesystem", "read", path="x")); assert False  # fichier absent
        except ToolError:
            pass


def test_write_read_list_inside_workspace_and_traversal_blocked():
    with tempfile.TemporaryDirectory() as d:
        b = box(d, {"filesystem": Permission.WRITE})
        run(b.call("filesystem", "write", path="src/main.py", content="print(1)"))
        assert run(b.call("filesystem", "read", path="src/main.py")) == "print(1)"
        assert run(b.call("filesystem", "list")) == ["src/"]
        for bad in ("../x", "/etc/passwd", "a/../../b", "~/x"):
            try:
                run(b.call("filesystem", "read", path=bad)); assert False, bad
            except ToolError:
                pass
        outside = Path(d).parent / "secret.txt"; outside.write_text("s")
        (Path(d) / "link").symlink_to(outside)
        try:
            run(b.call("filesystem", "read", path="link")); assert False
        except ToolError as e:
            assert "hors" in str(e)
        outside.unlink()


def test_delete_needs_human_approval_default_deny():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "f.txt").write_text("x"); log = []
        b = box(d, {"filesystem": Permission.WRITE}, log=log)
        try:
            run(b.call("filesystem", "delete", path="f.txt")); assert False
        except ApprovalDenied:
            pass
        assert (Path(d) / "f.txt").exists() and log[-1][0] == "tool.refused"
        seen = []
        async def yes(req): seen.append(req); return True
        b2 = box(d, {"filesystem": Permission.WRITE}, CallbackApprover(yes))
        run(b2.call("filesystem", "delete", path="f.txt"))
        assert not (Path(d) / "f.txt").exists() and "delete" in seen[0].summary and seen[0].agent == "t"


def test_memory_approval_store_waits_for_human_and_times_out_as_refusal():
    async def scenario():
        store = MemoryApprovalStore(timeout_s=1)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "f").write_text("x")
            b = box(d, {"filesystem": Permission.WRITE}, store)
            t = asyncio.create_task(b.call("filesystem", "delete", path="f"))
            await asyncio.sleep(0.05)
            assert len(store.pending) == 1
            assert store.decide(next(iter(store.pending)), True)
            await t
            assert not (Path(d) / "f").exists()
            (Path(d) / "g").write_text("x")
            quick = MemoryApprovalStore(timeout_s=0.05)
            try:
                await box(d, {"filesystem": Permission.WRITE}, quick).call("filesystem", "delete", path="g"); assert False
            except ApprovalDenied:
                pass
            assert (Path(d) / "g").exists() and not store.decide(999, True)
    run(scenario())


def test_calculator_is_safe():
    assert safe_eval("2 + 3 * (4 - 1) ** 2") == 29
    for bad in ("__import__('os').system('x')", "open('f')", "2 ** 9999", "1/0", "a + 1", "True + 1"):
        try:
            safe_eval(bad); assert False, bad
        except ToolError:
            pass


def test_python_tool_requires_execute_and_approval_and_reports_missing_docker():
    with tempfile.TemporaryDirectory() as d:
        try:
            run(box(d, {"python": Permission.READ}).call("python", "run", code="print(1)")); assert False
        except PermissionDenied:
            pass
        async def yes(req): return True
        b = box(d, {"python": Permission.EXECUTE}, CallbackApprover(yes))
        try:
            r = run(b.call("python", "run", code="print(1)"))
            assert r["exit_code"] == 0                 # Docker présent
        except ToolError as e:
            assert "Docker" in str(e)                  # Docker absent : erreur explicite, pas d'exécution locale


def test_git_tool_is_read_only_and_works():
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        b = box(d, {"git": Permission.READ})
        assert "##" in run(b.call("git", "status"))
        assert "diff" in b.registry.get("git").actions and "commit" not in b.registry.get("git").actions


def test_catalog_tool_references_are_known_to_the_registry():
    reg = default_registry(".")
    used = {t for a in Catalog.default() for t, _ in a.tools}
    assert used <= {t.name for t in reg.all()}, used - {t.name for t in reg.all()}
    planned = sorted(used - reg.available())
    assert planned == ["browser", "terminal", "web_search"]   # écart connu et documenté (docs/ROADMAP.md)
