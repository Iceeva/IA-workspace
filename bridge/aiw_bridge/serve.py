"""Servir un fichier GGUF local en un clic (§10, §11) : le bridge lance `llama-server` (llama.cpp) sur 127.0.0.1, attend qu'il
soit prêt, puis l'enregistre comme runtime — le modèle devient utilisable par les agents.

Sûreté : le fichier doit être dans un dossier de modèles autorisé (vérifié par l'appelant), le binaire est lancé sans shell,
l'écoute est limitée à 127.0.0.1 sur un port libre, le nombre de serveurs simultanés est borné et tout est arrêté à la sortie."""
from __future__ import annotations
import atexit
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MAX_SERVERS = 2
READY_TIMEOUT_S = 180
CTX_RANGE = (256, 262144)


class ServeError(ValueError):
    pass


def find_binary(env: dict | None = None) -> str | None:
    """`AIW_LLAMA_SERVER` (chemin explicite) sinon `llama-server` dans le PATH."""
    e = env if env is not None else os.environ
    p = e.get("AIW_LLAMA_SERVER")
    if p:
        return p if Path(p).is_file() else None
    return shutil.which("llama-server")


def slug(name: str) -> str:
    """Identifiant de modèle sûr (clé de routage, nom de runtime) tiré du nom de fichier."""
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\.gguf$", "", name, flags=re.I).lower()).strip("-")
    return s[:48] or "model"


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def build_cmd(binary: str, path: Path, port: int, ctx: int, ngl: int | None) -> list[str]:
    if not CTX_RANGE[0] <= ctx <= CTX_RANGE[1]:
        raise ServeError(f"Contexte hors limites ({CTX_RANGE[0]}–{CTX_RANGE[1]})")
    cmd = [binary, "-m", str(path), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx), "--alias", slug(path.name)]
    if ngl is not None:
        if not 0 <= ngl <= 999:
            raise ServeError("Couches GPU hors limites (0–999)")
        cmd += ["-ngl", str(ngl)]
    return cmd


@dataclass
class Served:
    id: str                      # identifiant du runtime enregistré (« gguf-<slug> »)
    model: str                   # nom du modèle côté runtime (alias)
    path: str
    port: int
    ctx: int
    status: str = "loading"      # loading | ready | failed | stopped
    error: str | None = None
    started: float = field(default_factory=time.time)
    _proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def to_dict(self) -> dict:
        return {"id": self.id, "model": self.model, "file": Path(self.path).name, "port": self.port, "ctx": self.ctx,
                "status": self.status, "error": self.error, "elapsed_s": int(time.time() - self.started)}


class Servers:
    def __init__(self, binary: str | None = None, on_ready=None, on_gone=None, ready_timeout_s: float = READY_TIMEOUT_S):
        self.binary, self.on_ready, self.on_gone, self.ready_timeout_s = binary, on_ready, on_gone, ready_timeout_s
        self.items: dict[str, Served] = {}
        self._lock = threading.Lock()
        atexit.register(self.stop_all)

    def start(self, path: Path, ctx: int = 4096, ngl: int | None = None) -> Served:
        bin_ = self.binary or find_binary()
        if not bin_:
            raise ServeError("llama-server est introuvable : installez llama.cpp ou définissez AIW_LLAMA_SERVER")
        if path.suffix.lower() != ".gguf":
            raise ServeError("Extension .gguf attendue")
        rid = f"gguf-{slug(path.name)}"
        with self._lock:
            cur = self.items.get(rid)
            if cur and cur.status in ("loading", "ready"):
                return cur                                           # déjà servi : idempotent
            if sum(1 for s in self.items.values() if s.status in ("loading", "ready")) >= MAX_SERVERS:
                raise ServeError(f"{MAX_SERVERS} modèles servis au maximum : arrêtez-en un d'abord")
            port = free_port()
            s = Served(rid, slug(path.name), str(path), port, ctx)
            cmd = build_cmd(bin_, path, port, ctx, ngl)
            try:
                s._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                raise ServeError(f"Lancement impossible : {e}")
            self.items[rid] = s
        threading.Thread(target=self._wait_ready, args=(s,), daemon=True).start()
        return s

    def _wait_ready(self, s: Served) -> None:
        deadline = time.time() + self.ready_timeout_s
        while time.time() < deadline and s.status == "loading":
            if s._proc and s._proc.poll() is not None:
                s.status, s.error = "failed", f"llama-server s'est arrêté (code {s._proc.returncode}) : mémoire insuffisante ou fichier incompatible ?"
                return
            try:
                with urllib.request.urlopen(s.base_url + "/health", timeout=2) as r:      # 200 = prêt, 503 = chargement en cours
                    if r.status == 200:
                        s.status = "ready"
                        if self.on_ready:
                            self.on_ready(s)
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.25)
        if s.status == "loading":
            s.status, s.error = "failed", "Délai dépassé au chargement du modèle"
            self._kill(s)

    @staticmethod
    def _kill(s: Served) -> None:
        if s._proc and s._proc.poll() is None:
            s._proc.terminate()
            try:
                s._proc.wait(5)
            except subprocess.TimeoutExpired:
                s._proc.kill()

    def stop(self, rid: str) -> bool:
        s = self.items.get(rid)
        if not s or s.status in ("stopped", "failed"):
            return False
        s.status = "stopped"
        self._kill(s)
        if self.on_gone:
            self.on_gone(s)
        return True

    def stop_all(self) -> None:
        for rid in list(self.items):
            self.stop(rid)
