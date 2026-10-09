"""Embeddings (§24). Deux implémentations derrière la même interface `embed(list[str]) -> list[vecteur]`.

• HashingEmbedder : hors ligne, déterministe, sans modèle. Il capte la ressemblance LEXICALE (mots et sous-mots
  partagés), pas la sémantique profonde : c'est un repli fonctionnel, pas un équivalent d'un modèle d'embeddings.
• OpenAICompatEmbedder : appelle /embeddings d'un serveur compatible OpenAI (OpenAI, Mistral, Ollama, LM Studio…)."""
from __future__ import annotations
import asyncio
import hashlib
import math
import re
from typing import Awaitable, Callable

_WORD = re.compile(r"\w+", re.U)


class EmbeddingError(RuntimeError):
    pass


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = 384):
        if dim < 16:
            raise ValueError("dim >= 16")
        self.dim = dim

    def _features(self, text: str):
        for w in _WORD.findall(text.lower()):
            yield w, 1.0
            if len(w) > 3:
                for i in range(len(w) - 2):  # trigrammes : « sécurité » ~ « sécuriser »
                    yield "#" + w[i:i + 3], 0.4

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for f, wgt in self._features(text):
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += wgt if (h >> 63) & 1 else -wgt   # signe pseudo-aléatoire : réduit les collisions
        return _norm(v)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


Post = Callable[[str, dict, dict], Awaitable[dict]]


async def _httpx_post(url: str, headers: dict, payload: dict) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        raise EmbeddingError(f"HTTP {r.status_code}")
    return r.json()


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, batch: int = 64, post: Post = _httpx_post):
        self.base_url, self.model, self.api_key, self.batch, self._post = base_url.rstrip("/"), model, api_key, batch, post
        self.name = f"{model}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = [t[:8000] or " " for t in texts[i:i + self.batch]]
            data = await self._post(f"{self.base_url}/embeddings", headers, {"model": self.model, "input": chunk})
            items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            if len(items) != len(chunk) or any("embedding" not in d for d in items):
                raise EmbeddingError("Réponse d'embeddings incohérente")
            out += [_norm([float(x) for x in d["embedding"]]) for d in items]
        return out
