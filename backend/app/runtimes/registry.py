"""Runtime Registry (§19) + détection des runtimes locaux (§10).

La détection sonde des adresses locales : elle est destinée au Local Bridge (machine de l'utilisateur) et ne doit
JAMAIS être exposée par l'API cloud (risque SSRF vers le réseau du serveur)."""
from __future__ import annotations
import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Awaitable, Callable

Fetch = Callable[[str, float], Awaitable[tuple[int, object | None]]]

# Capacités déclarées par type de runtime. Phonon et Sana sont enregistrables comme runtimes déclarés ; leurs
# adaptateurs (protocole d'appel) restent à écrire : le registre sait déjà router une capacité vers eux.
KIND_CAPS = {
    "ollama": {"chat", "code", "embedding"}, "lmstudio": {"chat", "code", "embedding"},
    "llamacpp": {"chat", "code"}, "localai": {"chat", "code", "embedding", "text-to-image", "speech-to-text"},
    "vllm": {"chat", "code"}, "openai_compat": {"chat", "code"},
    "phonon": {"speech-to-text"}, "sana": {"text-to-image"}, "custom": set()}


@dataclass
class RuntimeInfo:
    id: str
    kind: str
    name: str
    base_url: str
    status: str = "unknown"                 # connected | unreachable | unknown
    version: str | None = None
    models: list[str] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)
    platforms: tuple[str, ...] = ("Windows", "Linux", "Darwin")
    requirements: dict = field(default_factory=dict)
    latency_ms: int | None = None
    checked_at: float | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["capabilities"] = sorted(self.capabilities)
        return d


class RuntimeRegistry:
    def __init__(self):
        self._r: dict[str, RuntimeInfo] = {}

    def register(self, r: RuntimeInfo) -> None:
        if not r.capabilities:
            r.capabilities = set(KIND_CAPS.get(r.kind, set()))
        self._r[r.id] = r

    def unregister(self, rid: str) -> None:
        self._r.pop(rid, None)

    def get(self, rid: str) -> RuntimeInfo | None:
        return self._r.get(rid)

    def all(self) -> list[RuntimeInfo]:
        return sorted(self._r.values(), key=lambda r: r.id)

    def find(self, capability: str, *, connected_only: bool = True) -> list[RuntimeInfo]:
        """Runtimes capables de fournir `capability` (ex. « text-to-image » → Sana ou équivalent)."""
        return [r for r in self.all() if capability in r.capabilities and (r.status == "connected" or not connected_only)]


# (id, kind, nom, URL, chemin de sonde)
PROBES = [("ollama", "ollama", "Ollama", "http://127.0.0.1:11434", "/api/tags"),
          ("lmstudio", "lmstudio", "LM Studio", "http://127.0.0.1:1234", "/v1/models"),
          ("llamacpp-8080", "openai_compat", "Serveur OpenAI-compatible (llama.cpp / LocalAI) :8080",
           "http://127.0.0.1:8080", "/v1/models"),
          ("vllm", "vllm", "vLLM", "http://127.0.0.1:8000", "/v1/models")]


async def default_fetch(url: str, timeout: float) -> tuple[int, object | None]:
    def go():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — URL locale fixe
                return r.status, json.loads(r.read(2_000_000) or b"null")
        except OSError:
            return 0, None
        except ValueError:
            return 200, None
    return await asyncio.to_thread(go)


def parse_models(kind: str, payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if kind == "ollama":
        return [m.get("name", "") for m in payload.get("models", []) if isinstance(m, dict)]
    return [m.get("id", "") for m in payload.get("data", []) if isinstance(m, dict)]


async def probe(rid, kind, name, base_url, path, fetch: Fetch = default_fetch, timeout: float = 0.8) -> RuntimeInfo:
    t0 = time.monotonic()
    status, payload = await fetch(base_url + path, timeout)
    ok = 200 <= status < 300
    return RuntimeInfo(id=rid, kind=kind, name=name, base_url=base_url, status="connected" if ok else "unreachable",
                       models=[m for m in parse_models(kind, payload) if m] if ok else [],
                       capabilities=set(KIND_CAPS.get(kind, set())),
                       latency_ms=int((time.monotonic() - t0) * 1000) if ok else None, checked_at=time.time())


async def detect_local(registry: RuntimeRegistry, fetch: Fetch = default_fetch, probes=PROBES) -> list[RuntimeInfo]:
    """Sonde en parallèle les runtimes usuels, met à jour le registre, renvoie ceux qui répondent."""
    found = await asyncio.gather(*(probe(*p, fetch=fetch) for p in probes))
    for r in found:
        prev = registry.get(r.id)
        if r.status == "connected" or prev is None:
            registry.register(r)
        else:
            prev.status, prev.checked_at = "unreachable", r.checked_at
    return [r for r in found if r.status == "connected"]
