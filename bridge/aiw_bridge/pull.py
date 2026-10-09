"""Mode « pull » : le bridge se connecte AU serveur AI Workspace (sortant uniquement), récupère des tâches de chat
et les exécute sur les runtimes LOCAUX. Le serveur ne peut demander que du chat vers des modèles que vous exposez ;
aucune URL, aucun chemin de fichier, aucune commande n'est jamais acceptée dans une tâche."""
from __future__ import annotations
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .server import VERSION, Bridge

MAX_TOTAL_CHARS = 1_000_000
MAX_TOKENS = 8192
ROLES = {"system", "user", "assistant"}


def default_http(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, body, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — URL de serveur choisie par l'utilisateur
            return r.status, r.read(8_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(100_000)


class PullError(ValueError):
    pass


def validate_job(job: dict) -> dict:
    if not isinstance(job, dict) or job.get("type") != "chat" or not isinstance(job.get("id"), str):
        raise PullError("Type de tâche non pris en charge")
    msgs = job.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(job.get("model"), str) or not job["model"]:
        raise PullError("Tâche de chat invalide")
    total = 0
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ROLES or not isinstance(m.get("content"), str):
            raise PullError("Message invalide")
        total += len(m["content"])
    if total > MAX_TOTAL_CHARS:
        raise PullError("Tâche trop volumineuse")
    temp, mt = job.get("temperature", 0.2), job.get("max_tokens", 1024)
    if not isinstance(temp, (int, float)) or not 0 <= temp <= 2 or not isinstance(mt, int) or not 1 <= mt <= MAX_TOKENS:
        raise PullError("Paramètres de génération invalides")
    return {"model": job["model"], "messages": msgs, "temperature": temp, "max_tokens": mt}


class PullClient:
    def __init__(self, bridge: Bridge, server: str, api_key: str, org_id: str, http=default_http, wait_s: int = 20):
        u = urlsplit(server)
        if u.scheme != "https" and u.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Le serveur doit être en HTTPS (sauf localhost)")
        self.bridge, self.server, self.http, self.wait_s = bridge, server.rstrip("/"), http, wait_s
        self.headers = {"X-API-Key": api_key, "X-Organization-Id": org_id, "Content-Type": "application/json"}

    def _call(self, path: str, payload: dict, timeout: float) -> dict | None:
        status, raw = self.http("POST", self.server + path, self.headers, json.dumps(payload).encode(), timeout)
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        return json.loads(raw or b"null")

    def _models(self) -> tuple[list[str], list[str]]:
        self.bridge._detect()
        rts = [r for r in self.bridge.registry.all() if r.status == "connected"]
        return [f"{r.id}:{m}" for r in rts for m in r.models], [r.id for r in rts]

    def _execute(self, spec: dict) -> dict:
        rt, model = self.bridge.runtime_for(spec["model"])
        if rt is None or model not in rt.models:   # uniquement les modèles annoncés par ce bridge
            return {"ok": False, "error": "Modèle local introuvable sur ce bridge"}
        body = json.dumps({"model": model, "messages": spec["messages"], "temperature": spec["temperature"],
                           "max_tokens": spec["max_tokens"], "stream": False}).encode()
        try:
            status, raw = self.http("POST", rt.base_url.rstrip("/") + "/v1/chat/completions",
                                    {"Content-Type": "application/json"}, body, 600)
            if status >= 400:
                return {"ok": False, "error": f"Le runtime a répondu HTTP {status}"}
            data = json.loads(raw)
            usage = data.get("usage") or {}
            return {"ok": True, "content": data["choices"][0]["message"]["content"],
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)), "completion_tokens": int(usage.get("completion_tokens", 0))}
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            return {"ok": False, "error": f"Runtime : {type(e).__name__}"}

    def run_once(self) -> bool:
        models, runtimes = self._models()
        resp = self._call("/api/bridge/poll", {"models": models, "runtimes": runtimes, "version": VERSION,
                                               "wait_s": self.wait_s}, self.wait_s + 15)
        job = (resp or {}).get("data")
        if not job:
            return False
        try:
            result = self._execute(validate_job(job))
        except PullError as e:
            result = {"ok": False, "error": str(e)}
        self._call(f"/api/bridge/jobs/{job.get('id', 'x')}/result", result, 30)
        return True

    def run_forever(self, stop: threading.Event, backoff_s: float = 5.0) -> None:
        while not stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — réseau instable : on réessaie, sans jamais journaliser de contenu
                stop.wait(backoff_s)
