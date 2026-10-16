import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from aiw_bridge.pull import PullClient, PullError, validate_job  # noqa: E402
from aiw_bridge.server import Bridge, load_runtimes_file  # noqa: E402
from app.runtimes.registry import RuntimeInfo, RuntimeRegistry  # noqa: E402

TOKEN = "t" * 40


def bridge_with(models=("qwen3:8b",)):
    reg = RuntimeRegistry()
    reg.register(RuntimeInfo("ollama", "ollama", "Ollama", "http://127.0.0.1:11434", status="connected", models=list(models)))
    return Bridge(TOKEN, ["http://x"], [], reg, detect=lambda: None)


class FakeNet:
    """Simule le serveur AI Workspace et le runtime local."""
    def __init__(self, jobs): self.jobs, self.posted, self.runtime_calls = list(jobs), [], []

    def __call__(self, method, url, headers, body, timeout):
        if url.endswith("/api/bridge/poll"):
            assert headers["X-API-Key"] == "KEY" and headers["X-Organization-Id"] == "ORG"
            self.last_poll = json.loads(body)
            return 200, json.dumps({"success": True, "data": self.jobs.pop(0) if self.jobs else None}).encode()
        if "/api/bridge/jobs/" in url:
            self.posted.append((url.rsplit("/", 2)[1], json.loads(body))); return 200, b'{"success":true}'
        if url.endswith("/v1/chat/completions"):
            self.runtime_calls.append(json.loads(body))
            return 200, json.dumps({"choices": [{"message": {"content": "réponse locale"}}],
                                    "usage": {"prompt_tokens": 12, "completion_tokens": 5}}).encode()
        raise AssertionError(url)


JOB = {"id": "j1", "type": "chat", "model": "ollama:qwen3:8b", "temperature": 0.1, "max_tokens": 100,
       "messages": [{"role": "user", "content": "salut"}]}


def test_pull_cycle_executes_chat_on_local_runtime_and_reports_usage():
    net = FakeNet([JOB]); pc = PullClient(bridge_with(), "https://aiw.example", "KEY", "ORG", http=net)
    assert pc.run_once() is True and net.last_poll["models"] == ["ollama:qwen3:8b"] and net.last_poll["runtimes"] == ["ollama"]
    info = net.last_poll["runtime_info"]                                                              # fiche envoyée pour le registre persistant
    assert [i["id"] for i in info] == ["ollama"] and info[0]["models"] == ["qwen3:8b"] and info[0]["base_url"].startswith("http://")
    assert "api_key" not in json.dumps(info) and "requirements" not in info[0] and "path" not in info[0]
    assert net.posted == [("j1", {"ok": True, "content": "réponse locale", "prompt_tokens": 12, "completion_tokens": 5})]
    assert net.runtime_calls[0]["model"] == "qwen3:8b" and net.runtime_calls[0]["stream"] is False   # préfixe retiré
    assert pc.run_once() is False and len(net.posted) == 1                                            # file vide


def test_pull_rejects_anything_but_bounded_chat_jobs():
    for bad in ({**JOB, "type": "shell"}, {**JOB, "messages": []}, {**JOB, "max_tokens": 10 ** 9},
                {**JOB, "temperature": 9}, {**JOB, "messages": [{"role": "tool", "content": "x"}]},
                {**JOB, "messages": [{"role": "user", "content": "x" * 1_100_000}]}, {**JOB, "id": 5}, {"type": "chat"}):
        try:
            validate_job(bad); assert False, bad
        except PullError:
            pass
    try:
        validate_job({**JOB, "deadline": time.time() - 5}); assert False
    except PullError as e:
        assert "expirée" in str(e)
    validate_job({**JOB, "deadline": time.time() + 60})
    net = FakeNet([{**JOB, "type": "http", "url": "http://169.254.169.254"}])
    pc = PullClient(bridge_with(), "https://aiw.example", "KEY", "ORG", http=net)
    pc.run_once()
    assert net.posted[0][1]["ok"] is False and not net.runtime_calls                                 # rien n'a été exécuté


def test_pull_unknown_model_and_https_requirement():
    net = FakeNet([{**JOB, "model": "ollama:inconnu"}]); net_pc = PullClient(bridge_with(), "https://aiw.example", "KEY", "ORG", http=net)
    net_pc.run_once()
    assert net.posted[0][1] == {"ok": False, "error": "Modèle local introuvable sur ce bridge"}
    for url in ("http://aiw.example", "ftp://x"):
        try:
            PullClient(bridge_with(), url, "k", "o"); assert False
        except ValueError:
            pass
    PullClient(bridge_with(), "http://localhost:8000", "k", "o")                                      # localhost toléré


def test_runtimes_file_declares_phonon_and_sana_locally_only():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "runtimes.json"
        p.write_text(json.dumps([{"id": "phonon", "kind": "phonon", "base_url": "http://127.0.0.1:9001"},
                                 {"id": "sana", "kind": "sana", "base_url": "http://localhost:9000", "paths": {"image": "/gen"}}]))
        rts = load_runtimes_file(p)
        assert [r.id for r in rts] == ["phonon", "sana"] and rts[0].capabilities == {"speech-to-text"}
        assert rts[1].capabilities == {"text-to-image", "text-to-video"} and rts[1].requirements["paths"] == {"image": "/gen"}
        p.write_text(json.dumps([{"id": "evil", "kind": "custom", "base_url": "http://10.0.0.5:9"}]))
        try:
            load_runtimes_file(p); assert False
        except ValueError:
            pass
        assert load_runtimes_file(Path(d) / "absent.json") == []


def test_media_passthrough_routes_to_declared_runtime():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    got = {}
    class Up(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            got["path"], got["ct"], got["body"] = self.path, self.headers["Content-Type"], self.rfile.read(int(self.headers["Content-Length"]))
            got["auth"] = self.headers.get("Authorization")
            out = b'{"text":"bonjour"}' if "trans" in self.path else b'{"data":[{"b64_json":"eA=="}]}'
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{up.server_address[1]}"
    reg = RuntimeRegistry()
    reg.register(RuntimeInfo("phonon", "phonon", "Phonon", base, status="connected", requirements={"paths": {"stt": "/transcribe"}}))
    reg.register(RuntimeInfo("sana", "sana", "Sana", base, status="connected", requirements={"api_key": "sk-local"}))
    b = Bridge(TOKEN, ["https://app.example"], [], reg, detect=lambda: None)
    srv = b.serve(port=0); threading.Thread(target=srv.serve_forever, daemon=True).start()
    def post(path, data, ct, token=TOKEN):
        h = {"Host": f"127.0.0.1:{b.port}", "Content-Type": ct}
        if token: h["Authorization"] = f"Bearer {token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{b.port}{path}", data, h, method="POST"), timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    try:
        s, body = post("/v1/audio/transcriptions", b"--b\r\nWAVDATA\r\n--b--", "multipart/form-data; boundary=b")
        assert s == 200 and json.loads(body)["text"] == "bonjour" and got["path"] == "/transcribe" and got["ct"].startswith("multipart/")
        assert b"WAVDATA" in got["body"]
        assert got["auth"] is None                                   # Phonon sans clé : aucun en-tête ajouté
        s, body = post("/v1/videos/generations", json.dumps({"prompt": "chat", "duration": 5}).encode(), "application/json")
        assert s == 200 and got["path"] == "/v1/videos/generations" and got["auth"] == "Bearer sk-local"   # clé du runtime ajoutée par le bridge
        s, body = post("/v1/images/generations", json.dumps({"prompt": "chat"}).encode(), "application/json")
        assert s == 200 and got["path"] == "/v1/images/generations" and json.loads(got["body"])["prompt"] == "chat"
        assert post("/v1/audio/transcriptions", b"x", "audio/wav", token=None)[0] == 401
        assert post("/v1/audio/transcriptions", b"", "audio/wav")[0] == 413
        reg.unregister("phonon")
        assert post("/v1/audio/transcriptions", b"x", "audio/wav")[0] == 404
    finally:
        srv.shutdown(); up.shutdown()

def test_job_accepts_data_images_only():
    from aiw_bridge.pull import PullError, validate_job
    ok_part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    job = {"type": "chat", "id": "1", "model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}, ok_part]}]}
    assert validate_job(job)["messages"][0]["content"][1] == ok_part
    for bad_url in ("https://evil.example/x.png", "file:///etc/passwd", "data:text/html;base64,QUJD", "data:image/svg+xml;base64,QUJD"):
        bad = {**job, "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": bad_url}}]}]}
        try: validate_job(bad); assert False, bad_url
        except PullError: pass
    for bad_content in ([], [{"type": "tool", "x": 1}], "x"*0 or [{"type": "text"}]):
        try: validate_job({**job, "messages": [{"role": "user", "content": bad_content}]}); assert False
        except PullError: pass


def test_build_script_resolves_rust_target_triples():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_bridge", Path(__file__).resolve().parents[1] / "build_bridge.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    t = m.target_triple
    assert t("Windows", "AMD64") == "x86_64-pc-windows-msvc" and t("Darwin", "arm64") == "aarch64-apple-darwin"
    assert t("Linux", "x86_64") == "x86_64-unknown-linux-gnu"
    assert t("Linux", "x86_64", "rustc 1.80\nhost: aarch64-unknown-linux-gnu\n") == "aarch64-unknown-linux-gnu"   # rustc fait foi
    try:
        t("Plan9", "mips"); assert False
    except SystemExit:
        pass


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)

