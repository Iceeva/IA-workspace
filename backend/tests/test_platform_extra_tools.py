import asyncio
import base64
import sqlite3
import tempfile
from pathlib import Path

from app.catalog.model import Permission
from app.tools import extra
from app.tools.builtin import default_registry
from app.tools.registry import ApprovalDenied, CallbackApprover, PermissionDenied, ToolBox, ToolError


def run(c): return asyncio.run(c)


async def yes(req): return True


def box(reg, grants, approve=True):
    return ToolBox(reg, grants, approver=CallbackApprover(yes) if approve else None, agent="t") if approve else ToolBox(reg, grants, agent="t")


def err(coro, exc=ToolError):
    try:
        run(coro)
    except exc as e:
        return str(e)
    raise AssertionError("exception attendue")


def test_html_to_text_strips_scripts_and_resolves_links():
    h = ("<html><head><title>Doc</title><style>p{}</style></head><body><script>alert(1)</script>"
         "<h1>Titre</h1><p>Bonjour   <b>monde</b></p><a href='/x'>x</a><a href='javascript:evil()'>y</a></body></html>")
    r = extra.html_to_text(h, "https://site.example/a/")
    assert r["title"] == "Doc" and "alert" not in r["text"] and "Titre" in r["text"] and "Bonjour monde" in r["text"]
    assert r["links"] == ["https://site.example/x"]


def test_browser_and_http_tools_use_injected_client_and_gate_writes():
    calls = []
    async def http(method, url, headers, body):
        calls.append((method, url)); return 200, "<title>T</title><p>contenu</p>"
    reg = default_registry(".")
    reg.register(extra.browser_tool(http)); reg.register(extra.http_tool(http))
    b = box(reg, {"browser": Permission.READ, "http": Permission.WRITE})
    r = run(b.call("browser", "open", url="https://a.example"))
    assert r["title"] == "T" and "contenu" in r["text"]
    assert run(b.call("http", "get", url="https://a.example"))["status"] == 200
    run(b.call("http", "request", method="POST", url="https://a.example/h", body="x"))
    assert calls[-1] == ("POST", "https://a.example/h")
    assert "Méthode" in err(b.call("http", "request", method="GET", url="https://a.example"))
    nowrite = ToolBox(reg, {"http": Permission.WRITE})                       # sans approbateur : refus par défaut
    err(nowrite.call("http", "request", method="POST", url="https://a.example"), ApprovalDenied)
    err(ToolBox(reg, {"http": Permission.READ}).call("http", "request", method="POST", url="https://a.example"), PermissionDenied)


def test_real_http_tools_refuse_internal_addresses():
    reg = default_registry(".")
    b = box(reg, {"browser": Permission.READ, "http": Permission.READ})
    for url in ("http://169.254.169.254/latest/meta-data", "https://localhost/", "http://10.0.0.1/"):
        err(b.call("browser", "open", url=url), ToolError)


def test_web_search_requires_config_and_clamps_results():
    reg = default_registry(".")
    assert "non configurée" in err(box(reg, {"web_search": Permission.READ}).call("web_search", "search", query="x"))
    async def fj(url, headers=None):
        assert "q=caf%C3%A9" in url and url.endswith("format=json")
        return {"results": [{"title": f"t{i}", "url": f"https://r/{i}", "content": "c" * 500} for i in range(20)]}
    reg.register(extra.web_search_tool("http://searx:8080/search", fj))
    out = run(box(reg, {"web_search": Permission.READ}).call("web_search", "search", query="café", limit=50))
    assert len(out) == 10 and len(out[0]["snippet"]) == 300


def test_github_tool_validates_inputs_and_decodes_files():
    seen = []
    async def fj(url, headers=None):
        seen.append((url, headers))
        if "/contents/" in url:
            return {"encoding": "base64", "content": base64.b64encode("print('hé')".encode()).decode()}
        return [{"number": 1, "title": "Bug", "state": "open", "html_url": "https://github.com/a/b/issues/1"},
                {"number": 2, "title": "PR", "state": "open", "html_url": "u", "pull_request": {}}]
    reg = default_registry("."); reg.register(extra.github_tool("tok", fj))
    b = box(reg, {"github": Permission.READ})
    issues = run(b.call("github", "issues", repo="acme/api"))
    assert [i["pull_request"] for i in issues] == [False, True] and seen[0][1]["Authorization"] == "Bearer tok"
    assert run(b.call("github", "file", repo="acme/api", path="src/a.py", ref="main")) == "print('hé')"
    for bad in ({"repo": "evil/../x"}, {"repo": "a b/c"}, {"repo": "https://x/y"}):
        err(b.call("github", "issues", **bad))
    err(b.call("github", "file", repo="acme/api", path="../../etc/passwd"))
    err(b.call("github", "issues", repo="acme/api", state="weird"))
    assert "write" not in reg.get("github").actions                         # lecture seule par construction


def test_database_tool_is_read_only_and_confined():
    with tempfile.TemporaryDirectory() as d:
        con = sqlite3.connect(Path(d) / "app.db"); con.execute("create table t(a, b)")
        con.executemany("insert into t values (?, ?)", [(i, f"v{i}") for i in range(300)]); con.commit(); con.close()
        outside = Path(d).parent / "other.db"; sqlite3.connect(outside).close()
        reg = default_registry(d); b = box(reg, {"database": Permission.READ})
        assert run(b.call("database", "tables", db="app.db")) == ["t"]
        r = run(b.call("database", "query", db="app.db", sql="select * from t where a < 3 order by a"))
        assert r["columns"] == ["a", "b"] and len(r["rows"]) == 3
        assert len(run(b.call("database", "query", db="app.db", sql="select * from t", limit=9999))["rows"]) == 200
        for sql in ("delete from t", "insert into t values (1,2)", "drop table t", "select 1; drop table t",
                    "pragma writable_schema=1", "attach database 'x' as y", "select * from nope"):
            err(b.call("database", "query", db="app.db", sql=sql))
        assert run(b.call("database", "query", db="app.db", sql="select count(*) from t"))["rows"] == [[300]]
        for p in ("../other.db", "/etc/passwd", "absent.db"):
            err(b.call("database", "tables", db=p))
        outside.unlink()


def test_email_tool_validates_and_needs_approval_and_config():
    sent = []
    async def sender(to, subject, body): sent.append((to, subject))
    reg = default_registry("."); reg.register(extra.email_tool(sender))
    b = box(reg, {"email": Permission.WRITE})
    assert "envoyé" in run(b.call("email", "send", to="a@b.io", subject="Hi", body="x")) and sent == [("a@b.io", "Hi")]
    err(b.call("email", "send", to="pas-un-mail", subject="x", body="y"))
    err(b.call("email", "send", to="a@b.io", subject="x\nBcc: evil@x.io", body="y"))          # injection d'en-tête
    err(ToolBox(reg, {"email": Permission.WRITE}).call("email", "send", to="a@b.io", subject="x", body="y"), ApprovalDenied)
    try:
        import pydantic_settings  # noqa: F401  (le vrai mailer lit la configuration de l'application)
    except ImportError:
        return
    reg2 = default_registry(".")                                                              # vrai mailer, sans SMTP
    assert "SMTP" in err(box(reg2, {"email": Permission.WRITE}).call("email", "send", to="a@b.io", subject="x", body="y"))


def test_pdf_and_image_tools():
    with tempfile.TemporaryDirectory() as d:
        content = b"BT /F1 24 Tf 72 700 Td (Bonjour PDF) Tj ET"
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        out, offs = b"%PDF-1.4\n", []
        for i, o in enumerate(objs, 1):
            offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        x = len(out); out += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offs)
        out += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % x
        (Path(d) / "a.pdf").write_bytes(out)
        from PIL import Image
        Image.new("RGB", (200, 100), "red").save(Path(d) / "i.png")
        reg = default_registry(d); b = box(reg, {"pdf": Permission.READ, "image": Permission.WRITE})
        r = run(b.call("pdf", "extract", path="a.pdf"))
        assert r["pages"] == 1 and "Bonjour PDF" in r["text"]
        err(b.call("pdf", "extract", path="../x.pdf"))
        assert run(b.call("image", "info", path="i.png")) == {"format": "PNG", "width": 200, "height": 100, "mode": "RGB"}
        run(b.call("image", "resize", path="i.png", out="out/s.png", width=50))
        assert run(b.call("image", "info", path="out/s.png"))["height"] == 25
        err(b.call("image", "resize", path="i.png", out="s.png", width=999999))
        err(b.call("image", "info", path="../i.png"))


def test_deploy_hooks_are_named_and_never_agent_supplied():
    hit = []
    async def http(method, url, headers, body): hit.append((method, url)); return 200, "ok"
    reg = default_registry("."); reg.register(extra.deploy_tool({"staging": "https://hooks.example/abc"}, http))
    b = box(reg, {"deploy": Permission.EXECUTE})
    assert run(b.call("deploy", "trigger", target="staging"))["status"] == 200 and hit == [("POST", "https://hooks.example/abc")]
    assert "staging" in err(b.call("deploy", "trigger", target="https://evil.example/x"))
    err(ToolBox(reg, {"deploy": Permission.EXECUTE}).call("deploy", "trigger", target="staging"), ApprovalDenied)


def test_terminal_javascript_automation_rag_tools():
    async def wf(name, payload): return f"lancé {name} {payload}"
    async def rs(q, k): return [{"q": q, "k": k}]
    reg = default_registry(".", run_workflow=wf, rag_search=rs)
    b = box(reg, {"terminal": Permission.EXECUTE, "automation": Permission.EXECUTE, "rag": Permission.READ, "javascript": Permission.EXECUTE})
    assert run(b.call("automation", "run_workflow", name="nightly", payload={"a": 1})) == "lancé nightly {'a': 1}"
    assert run(b.call("rag", "search", query="x", k=99)) == [{"q": "x", "k": 10}]
    try:
        r = run(b.call("terminal", "run", command="echo salut"))
        assert r["exit_code"] == 0 and "salut" in r["stdout"]
    except ToolError as e:
        assert "Docker" in str(e)                      # sans Docker : refus explicite, jamais d'exécution sur l'hôte
    assert "terminal" in reg.get("terminal").to_dict()["name"] and "hôte" in reg.get("terminal").description
