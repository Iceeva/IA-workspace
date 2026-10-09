"""AI Workspace Local Bridge (§12, §15) : passerelle locale entre l'application (navigateur) et les runtimes de
la machine (Ollama, LM Studio, llama.cpp, vLLM…), les fichiers GGUF et le profil matériel.

Sécurité (le bridge expose votre machine à une page web : chaque point compte) :
  • écoute uniquement sur 127.0.0.1 ;
  • jeton d'appairage obligatoire (Bearer) sur tout sauf /health ;
  • en-tête Origin vérifié contre une liste d'origines autorisées (sinon 403) + en-tête Host vérifié (anti DNS-rebinding) ;
  • le proxy n'atteint QUE les runtimes détectés/enregistrés (jamais d'URL fournie par le client → pas de SSRF) ;
  • lecture de GGUF limitée aux dossiers de modèles autorisés ;
  • rien n'est journalisé du contenu des requêtes.
Stdlib uniquement ; réutilise les modules app.runtimes du backend (PYTHONPATH=backend)."""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.runtimes import gguf, hardware
from app.runtimes.registry import KIND_CAPS, RuntimeInfo, RuntimeRegistry, detect_local

VERSION = "0.1.0"
MAX_BODY = 5 * 1024 * 1024
MAX_MEDIA_BODY = 60 * 1024 * 1024     # audio entrant (transcription)
# route du bridge → (capacité requise, chemin chez le runtime). Le chemin peut être surchargé dans runtimes.json.
MEDIA_ROUTES = {"/v1/audio/transcriptions": ("speech-to-text", "stt"), "/v1/images/generations": ("text-to-image", "image")}


def load_runtimes_file(path: str | Path) -> list[RuntimeInfo]:
    """Runtimes déclarés (Phonon, Sana, autres) : [{id, kind, name, base_url, capabilities?, paths?:{stt,image}}]."""
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    out = []
    for d in json.loads(p.read_text(encoding="utf-8")):
        url = str(d["base_url"])
        if not url.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise ValueError(f"Runtime {d.get('id')}: seules les adresses locales sont autorisées")
        out.append(RuntimeInfo(id=str(d["id"]), kind=d.get("kind", "custom"), name=d.get("name", d["id"]), base_url=url,
                               status="connected", capabilities=set(d.get("capabilities") or KIND_CAPS.get(d.get("kind", "custom"), set())),
                               requirements={"paths": d.get("paths", {})}))
    return out


class Bridge:
    def __init__(self, token: str, allowed_origins: list[str], models_dirs: list[str] | None = None,
                 registry: RuntimeRegistry | None = None, detect=None):
        if len(token) < 24:
            raise ValueError("Jeton d'appairage trop court")
        self.token, self.origins = token, set(allowed_origins)
        self.models_dirs = [Path(d).resolve() for d in (models_dirs or [])]
        self.registry = registry or RuntimeRegistry()
        self._detect = detect or (lambda: asyncio.run(detect_local(self.registry)))
        self.port = 0

    # -- helpers -----------------------------------------------------------------------------
    def authorized(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[7:].encode(), self.token.encode())

    def resolve_gguf(self, raw: str) -> Path:
        p = Path(raw).expanduser().resolve()
        if not any(d == p or d in p.parents for d in self.models_dirs):
            raise PermissionError("Fichier hors des dossiers de modèles autorisés")
        if not p.is_file():
            raise FileNotFoundError("Fichier introuvable")
        return p

    def list_gguf(self) -> list[Path]:
        out: list[Path] = []
        for d in self.models_dirs:
            if d.is_dir():
                out += [p for p in d.rglob("*.gguf") if len(p.relative_to(d).parts) <= 3]
        return sorted(out)

    def runtime_for(self, model: str):
        """« runtimeId:modèle » → (runtime, modèle). Sans préfixe : premier runtime connecté qui expose ce modèle."""
        if ":" in model:
            rid, _, m = model.partition(":")
            r = self.registry.get(rid)
            if r and r.status == "connected":
                return r, m
        for r in self.registry.all():
            if r.status == "connected" and model in r.models:
                return r, model
        return None, model

    def media_runtime(self, capability: str, wanted: str | None):
        cands = self.registry.find(capability)
        if wanted:
            cands = [r for r in cands if r.id == wanted]
        return cands[0] if cands else None

    def serve(self, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
        srv = ThreadingHTTPServer((host, port), _handler(self))
        self.port = srv.server_address[1]
        return srv


def _handler(b: Bridge):
    class H(BaseHTTPRequestHandler):
        server_version = f"aiw-bridge/{VERSION}"

        def log_message(self, *a):  # aucun journal d'accès : les requêtes contiennent des prompts
            pass

        # -- réponse ----------------------------------------------------------------------------
        def _cors(self):
            o = self.headers.get("Origin")
            if o and o in b.origins:
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                if self.headers.get("Access-Control-Request-Private-Network") == "true":
                    self.send_header("Access-Control-Allow-Private-Network", "true")

        def _json(self, status: int, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _err(self, status: int, code: str, msg: str):
            self._json(status, {"success": False, "error": {"code": code, "message": msg}})

        # -- garde-fous ----------------------------------------------------------------------------
        def _guard(self, need_auth: bool = True) -> bool:
            host = (self.headers.get("Host") or "").lower()
            if host not in (f"127.0.0.1:{b.port}", f"localhost:{b.port}"):
                self._err(403, "BAD_HOST", "Hôte non autorisé"); return False
            o = self.headers.get("Origin")
            if o and o not in b.origins:
                self._err(403, "BAD_ORIGIN", "Origine non autorisée"); return False
            if need_auth and not b.authorized(self.headers.get("Authorization")):
                self._err(401, "UNAUTHORIZED", "Jeton d'appairage invalide"); return False
            return True

        def _body(self) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    self._err(413, "TOO_LARGE", "Requête trop volumineuse"); return None
                return json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._err(400, "BAD_JSON", "JSON invalide"); return None

        # -- routes ------------------------------------------------------------------------------
        def do_OPTIONS(self):
            if not self._guard(need_auth=False):
                return
            self.send_response(204); self._cors(); self.send_header("Content-Length", "0"); self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/health":
                if self._guard(False):
                    self._json(200, {"ok": True, "name": "ai-workspace-bridge", "version": VERSION})
                return
            if not self._guard():
                return
            if path == "/hardware":
                self._json(200, {"success": True, "data": hardware.detect().to_dict()})
            elif path == "/runtimes":
                b._detect()
                self._json(200, {"success": True, "data": [r.to_dict() for r in b.registry.all()]})
            elif path == "/models":
                b._detect()
                self._json(200, {"success": True, "data": [
                    {"key": f"{r.id}:{m}", "runtime": r.id, "model": m, "local": True}
                    for r in b.registry.all() if r.status == "connected" for m in r.models]})
            elif path == "/gguf":
                hw = hardware.detect()
                rows = []
                for p in b.list_gguf():
                    try:
                        info = gguf.inspect(p)
                    except gguf.GGUFError as e:
                        rows.append({"file_name": p.name, "error": str(e)}); continue
                    d = info.to_dict(); d["path"] = str(p); d["fit"] = hardware.fit(hw, d["memory_needed_gb"])
                    rows.append(d)
                self._json(200, {"success": True, "data": rows})
            else:
                self._err(404, "NOT_FOUND", "Route inconnue")

        def do_POST(self):
            path = self.path.split("?")[0]
            if not self._guard():
                return
            if path in MEDIA_ROUTES:
                return self._media(path)
            body = self._body()
            if body is None:
                return
            if path == "/gguf/inspect":
                try:
                    info = gguf.inspect(b.resolve_gguf(str(body.get("path", ""))))
                except PermissionError as e:
                    return self._err(403, "FORBIDDEN_PATH", str(e))
                except FileNotFoundError as e:
                    return self._err(404, "NOT_FOUND", str(e))
                except gguf.GGUFError as e:
                    return self._err(422, "BAD_GGUF", str(e))
                d = info.to_dict(body.get("ctx")); d["fit"] = hardware.fit(hardware.detect(), d["memory_needed_gb"])
                return self._json(200, {"success": True, "data": d})
            if path == "/v1/chat/completions":
                return self._proxy(body)
            self._err(404, "NOT_FOUND", "Route inconnue")

        def _media(self, path: str):
            """Transmet tel quel (multipart ou JSON) vers le runtime local déclaré pour cette capacité."""
            cap, key = MEDIA_ROUTES[path]
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_MEDIA_BODY:
                return self._err(413, "TOO_LARGE", "Corps absent ou trop volumineux")
            rt = b.media_runtime(cap, self.headers.get("X-AIW-Runtime"))
            if rt is None:
                return self._err(404, "RUNTIME_NOT_FOUND", f"Aucun runtime local déclaré pour « {cap} »")
            target = rt.base_url.rstrip("/") + (rt.requirements.get("paths", {}).get(key) or path)
            req = urllib.request.Request(target, self.rfile.read(n), {
                "Content-Type": self.headers.get("Content-Type", "application/octet-stream")}, method="POST")
            try:
                up = urllib.request.urlopen(req, timeout=600)  # noqa: S310 — cible issue du registre local
            except urllib.error.HTTPError as e:
                return self._err(502, "UPSTREAM_ERROR", f"Le runtime a répondu HTTP {e.code}")
            except OSError:
                return self._err(502, "UPSTREAM_UNREACHABLE", "Runtime injoignable")
            with up:
                data = up.read(MAX_MEDIA_BODY)
            self.send_response(200)
            self.send_header("Content-Type", up.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _proxy(self, body: dict):
            rt, model = b.runtime_for(str(body.get("model", "")))
            if rt is None:
                b._detect()
                rt, model = b.runtime_for(str(body.get("model", "")))
            if rt is None:
                return self._err(404, "RUNTIME_NOT_FOUND", "Aucun runtime local connecté ne fournit ce modèle")
            payload = json.dumps({**body, "model": model}).encode()
            url = rt.base_url.rstrip("/") + "/v1/chat/completions"
            req = urllib.request.Request(url, payload, {"Content-Type": "application/json"}, method="POST")
            try:
                up = urllib.request.urlopen(req, timeout=600)  # noqa: S310 — URL issue du registre local, pas du client
            except urllib.error.HTTPError as e:
                return self._err(502, "UPSTREAM_ERROR", f"Le runtime a répondu HTTP {e.code}")
            except OSError:
                return self._err(502, "UPSTREAM_UNREACHABLE", "Runtime injoignable")
            with up:
                self.send_response(up.status)
                self.send_header("Content-Type", up.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self._cors()
                self.end_headers()
                while chunk := up.read(4096):
                    self.wfile.write(chunk); self.wfile.flush()
            self.close_connection = True
    return H


def load_or_create_token(path: str | Path) -> str:
    p = Path(path).expanduser()
    if p.is_file():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t)
    return t


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="AI Workspace Local Bridge")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--origin", action="append", default=[], help="origine autorisée (ex. https://ai-workspace.example.com)")
    ap.add_argument("--models-dir", action="append", default=[], help="dossier de modèles GGUF autorisé")
    ap.add_argument("--token-file", default="~/.ai-workspace/bridge-token")
    ap.add_argument("--runtimes-file", default="~/.ai-workspace/runtimes.json",
                    help="runtimes locaux déclarés (Phonon, Sana, …)")
    ap.add_argument("--server", help="mode pull : URL de l'API AI Workspace (https://…)")
    ap.add_argument("--org", help="mode pull : identifiant d'organisation")
    ap.add_argument("--api-key", default=os.environ.get("AIW_API_KEY"), help="mode pull : clé API (ou AIW_API_KEY)")
    a = ap.parse_args(argv)
    origins = a.origin or ["http://localhost:4200"]
    bridge = Bridge(load_or_create_token(a.token_file), origins, a.models_dir)
    for r in load_runtimes_file(a.runtimes_file):
        bridge.registry.register(r)
    if a.server:
        if not (a.org and a.api_key):
            ap.error("--server exige --org et --api-key (ou AIW_API_KEY)")
        from .pull import PullClient
        pc = PullClient(bridge, a.server, a.api_key, a.org)
        threading.Thread(target=pc.run_forever, args=(threading.Event(),), daemon=True).start()
        print(f"Mode pull actif vers {a.server} : le serveur peut utiliser vos modèles locaux (chat uniquement).")
    srv = bridge.serve(port=a.port)
    print(f"Local Bridge sur http://127.0.0.1:{bridge.port}\nOrigines autorisées : {', '.join(origins)}\n"
          f"Jeton d'appairage (à coller dans AI Workspace) : {bridge.token}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
