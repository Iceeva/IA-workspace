import json
import struct
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from aiw_bridge.server import Bridge, load_or_create_token  # noqa: E402
from app.runtimes.registry import RuntimeInfo, RuntimeRegistry  # noqa: E402

TOKEN = "t" * 40
ORIGIN = "https://ai-workspace.example.com"


class Upstream(BaseHTTPRequestHandler):
    seen = []
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Upstream.seen.append(body)
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for w in ("Bon", "jour"):
                self.wfile.write(f'data: {{"choices":[{{"delta":{{"content":"{w}"}}}}]}}\n\n'.encode()); self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            out = json.dumps({"choices": [{"message": {"content": "local:" + body["model"]}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


def start(models_dir):
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    reg = RuntimeRegistry()
    reg.register(RuntimeInfo("ollama", "ollama", "Ollama", f"http://127.0.0.1:{up.server_address[1]}",
                             status="connected", models=["qwen3:8b"]))
    b = Bridge(TOKEN, [ORIGIN], [models_dir], reg, detect=lambda: None)
    srv = b.serve(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return b, srv, up


def call(b, path, method="GET", body=None, token=TOKEN, origin=None, host=None, headers=None, raw=None):
    h = {"Host": host or f"127.0.0.1:{b.port}"}
    if token: h["Authorization"] = f"Bearer {token}"
    if origin: h["Origin"] = origin
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data: h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{b.port}{path}", data, h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _s(x): b = x.encode(); return struct.pack("<Q", len(b)) + b


def make_gguf(p):
    kv = [("general.architecture", 8, _s("llama")), ("general.name", 8, _s("Tiny-Instruct")),
          ("llama.context_length", 4, struct.pack("<I", 2048))]
    body = b"".join(_s(k) + struct.pack("<I", t) + v for k, t, v in kv)
    p.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 1, len(kv)) + body + b"\0" * 100)


def test_bridge_end_to_end():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
        make_gguf(Path(d) / "Tiny-Q4_K_M.gguf"); make_gguf(Path(other) / "secret.gguf")
        b, srv, up = start(d)
        try:
            # santé : sans jeton, mais avec contrôle d'hôte/origine
            s, _, body = call(b, "/health", token=None); assert s == 200 and json.loads(body)["ok"]
            assert call(b, "/health", token=None, host="evil.example:80")[0] == 403          # DNS rebinding
            assert call(b, "/health", token=None, origin="https://evil.example")[0] == 403   # origine inconnue
            # authentification
            assert call(b, "/hardware", token=None)[0] == 401 and call(b, "/hardware", token="x" * 40)[0] == 401
            s, _, body = call(b, "/hardware"); assert s == 200 and json.loads(body)["data"]["threads"] >= 1
            # CORS + Private Network Access
            s, h, _ = call(b, "/hardware", method="OPTIONS", token=None, origin=ORIGIN,
                           headers={"Access-Control-Request-Private-Network": "true"})
            assert s == 204 and h["Access-Control-Allow-Origin"] == ORIGIN and h["Access-Control-Allow-Private-Network"] == "true"
            assert call(b, "/hardware", origin=ORIGIN)[1]["Access-Control-Allow-Origin"] == ORIGIN
            # modèles et runtimes
            s, _, body = call(b, "/models"); assert json.loads(body)["data"][0]["key"] == "ollama:qwen3:8b"
            # GGUF : listing limité au dossier autorisé, inspection et refus hors périmètre
            s, _, body = call(b, "/gguf"); rows = json.loads(body)["data"]
            assert [r["file_name"] for r in rows] == ["Tiny-Q4_K_M.gguf"] and rows[0]["quantization"] == "Q4_K_M" and rows[0]["fit"]
            s, _, body = call(b, "/gguf/inspect", "POST", {"path": rows[0]["path"], "ctx": 2048}); assert s == 200
            assert call(b, "/gguf/inspect", "POST", {"path": str(Path(other) / "secret.gguf")})[0] == 403
            assert call(b, "/gguf/inspect", "POST", {"path": str(Path(d) / ".." / Path(other).name / "secret.gguf")})[0] == 403
            assert call(b, "/gguf/inspect", "POST", {"path": str(Path(d) / "nope.gguf")})[0] == 404
            # proxy de chat : non-stream, stream, runtime inconnu, jamais d'URL client
            s, _, body = call(b, "/v1/chat/completions", "POST", {"model": "ollama:qwen3:8b", "messages": []})
            assert json.loads(body)["choices"][0]["message"]["content"] == "local:qwen3:8b"
            assert Upstream.seen[-1]["model"] == "qwen3:8b"                                  # préfixe retiré
            s, _, body = call(b, "/v1/chat/completions", "POST", {"model": "qwen3:8b", "stream": True, "messages": []})
            assert s == 200 and body.count(b"data: ") == 3 and b"[DONE]" in body
            assert call(b, "/v1/chat/completions", "POST", {"model": "inconnu"})[0] == 404
            n = len(Upstream.seen)   # un « base_url » fourni par le client n'est jamais utilisé comme destination
            s, _, _ = call(b, "/v1/chat/completions", "POST", {"model": "ollama:x", "base_url": "http://169.254.169.254"})
            assert s == 200 and len(Upstream.seen) == n + 1                  # c'est bien le runtime enregistré qui a répondu
            assert call(b, "/nope")[0] == 404
            assert call(b, "/gguf/inspect", "POST", raw=b"{pas du json")[0] == 400
        finally:
            srv.shutdown(); up.shutdown()


def test_token_file_is_created_private_and_reused():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sub" / "tok"
        t1 = load_or_create_token(p); assert len(t1) >= 40 and (p.stat().st_mode & 0o777) == 0o600
        assert load_or_create_token(p) == t1
    for bad in ("short",):
        try:
            Bridge(bad, []); assert False
        except ValueError:
            pass


if __name__ == "__main__":
    test_bridge_end_to_end(); test_token_file_is_created_private_and_reused(); print("bridge OK")
