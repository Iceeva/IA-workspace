import json
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2] / "backend")]
from aiw_bridge.serve import ServeError, Servers, build_cmd, find_binary, free_port, slug  # noqa: E402
from aiw_bridge.server import Bridge  # noqa: E402

TOKEN = "t" * 40


def fake_llama_server(d: Path, *, crash=False, load_s=0.4) -> str:
    """Faux llama-server : écoute sur --port, /health répond 503 pendant le chargement puis 200."""
    p = d / "fake-llama-server"
    p.write_text(f"#!{sys.executable}\nimport sys, time, threading\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
                 + ("sys.exit(3)\n" if crash else "") +
                 "a = sys.argv; port = int(a[a.index('--port') + 1]); t0 = time.time()\n"
                 "assert a[a.index('--host') + 1] == '127.0.0.1'\n"
                 "class H(BaseHTTPRequestHandler):\n"
                 "    def log_message(self, *x): pass\n"
                 "    def do_GET(self):\n"
                 f"        ok = time.time() - t0 > {load_s}\n"
                 "        self.send_response(200 if ok else 503); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}')\n"
                 "HTTPServer(('127.0.0.1', port), H).serve_forever()\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def wait_for(cond, secs=10):
    t = time.time()
    while not cond() and time.time() - t < secs:
        time.sleep(0.05)
    return cond()


def test_slug_and_command_are_safe():
    assert slug("Qwen3-8B-Q4_K_M.gguf") == "qwen3-8b-q4-k-m" and slug("../../etc/passwd; rm -rf.gguf") == "etc-passwd-rm-rf" and slug("???.gguf") == "model"
    c = build_cmd("/bin/ls", Path("/m/a.gguf"), 9, 4096, 99)
    assert c[:3] == ["/bin/ls", "-m", "/m/a.gguf"] and "127.0.0.1" in c and c[c.index("-ngl") + 1] == "99" and c[c.index("--alias") + 1] == "a"
    for ctx, ngl in ((10, None), (999999999, None), (4096, -1), (4096, 5000)):
        try:
            build_cmd("x", Path("a.gguf"), 1, ctx, ngl); assert False
        except ServeError:
            pass
    assert free_port() > 0 and find_binary({"AIW_LLAMA_SERVER": "/nope"}) is None


def test_serve_lifecycle_ready_registered_idempotent_limited_and_stopped():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); events = []
        for n in ("a", "b", "c"):
            (d / f"{n}.gguf").write_bytes(b"GGUF")
        sv = Servers(fake_llama_server(d), on_ready=lambda s: events.append(("ready", s.id)), on_gone=lambda s: events.append(("gone", s.id)))
        s = sv.start(d / "a.gguf", 2048)
        assert s.status == "loading" and sv.start(d / "a.gguf", 2048) is s                    # idempotent
        assert wait_for(lambda: s.status == "ready") and ("ready", "gguf-a") in events
        with urllib.request.urlopen(s.base_url + "/health", timeout=3) as r:
            assert r.status == 200
        sv.start(d / "b.gguf")
        try:
            sv.start(d / "c.gguf"); assert False                                                # 2 serveurs au plus
        except ServeError as e:
            assert "maximum" in str(e)
        assert sv.stop("gguf-a") and ("gone", "gguf-a") in events and s.status == "stopped" and not sv.stop("gguf-a")
        assert wait_for(lambda: s._proc.poll() is not None)
        sv.stop_all()


def test_serve_reports_crash_and_timeout():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); (d / "a.gguf").write_bytes(b"GGUF")
        sv = Servers(fake_llama_server(d, crash=True)); s = sv.start(d / "a.gguf")
        assert wait_for(lambda: s.status == "failed") and "mémoire insuffisante" in s.error
        slow = Servers(fake_llama_server(d, load_s=60), ready_timeout_s=1); s2 = slow.start(d / "a.gguf")
        assert wait_for(lambda: s2.status == "failed", 6) and "Délai" in s2.error and wait_for(lambda: s2._proc.poll() is not None)
        try:
            Servers(None).start(d / "a.gguf") if find_binary({}) is None else None
        except ServeError as e:
            assert "introuvable" in str(e)


def test_bridge_serve_endpoint_registers_runtime_and_guards_paths():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
        d, other = Path(d), Path(other)
        (d / "m.gguf").write_bytes(b"GGUF"); (other / "x.gguf").write_bytes(b"GGUF")
        b = Bridge(TOKEN, ["https://app.example"], [str(d)], detect=lambda: None)
        b.servers.binary = fake_llama_server(d)
        srv = b.serve(port=0); threading.Thread(target=srv.serve_forever, daemon=True).start()
        def call(path, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{b.port}{path}", json.dumps(body).encode() if body is not None else None,
                                         {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "Host": f"127.0.0.1:{b.port}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            assert call("/serve", {"path": str(other / "x.gguf")})[0] == 403
            assert call("/serve", {"path": str(d / "m.gguf"), "ctx": 5})[0] == 422
            s, r = call("/serve", {"path": str(d / "m.gguf"), "ctx": 4096}); assert s == 202 and r["data"]["id"] == "gguf-m"
            assert wait_for(lambda: b.registry.get("gguf-m") is not None)
            rt = b.registry.get("gguf-m")
            assert rt.status == "connected" and rt.models == ["m"] and "chat" in rt.capabilities and rt.base_url.startswith("http://127.0.0.1:")
            s, r = call("/serve"); assert r["data"]["servers"][0]["status"] == "ready" and r["data"]["available"]
            assert call("/serve/stop", {"id": "gguf-m"})[1]["data"]["stopped"] and b.registry.get("gguf-m") is None
        finally:
            b.servers.stop_all(); srv.shutdown()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
