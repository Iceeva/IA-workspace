"""Recherche vectorielle + lexicale fusionnées (RRF). Calcul en Python : adapté jusqu'à quelques dizaines de milliers
de passages par recherche ; au-delà, déplacez le calcul dans pgvector (voir docs/ROADMAP.md)."""
from __future__ import annotations
import math
from collections import Counter
from dataclasses import dataclass

from app.catalog.text import tokens


@dataclass
class Doc:
    id: object
    text: str
    vec: list[float] | None = None
    meta: dict | None = None


@dataclass
class Hit:
    doc: Doc
    score: float
    vector_rank: int | None
    keyword_rank: int | None


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # vecteurs déjà normalisés


def keyword_scores(query: str, docs: list[Doc]) -> list[float]:
    q = set(tokens(query))
    if not q:
        return [0.0] * len(docs)
    toks = [Counter(tokens(d.text)) for d in docs]
    df = Counter(t for c in toks for t in c if t in q)
    n = max(1, len(docs))
    out = []
    for c in toks:
        out.append(sum((1 + math.log(c[t])) * math.log(1 + n / df[t]) for t in q if c.get(t)))
    return out


def hybrid_search(query: str, qvec: list[float] | None, docs: list[Doc], k: int = 5, *, rrf_k: int = 60,
                  min_vector: float = 0.05) -> list[Hit]:
    """Fusion par rang réciproque (RRF) du classement vectoriel et du classement lexical."""
    if not docs:
        return []
    kw = keyword_scores(query, docs)
    kw_rank = {i: r for r, (i, s) in enumerate(sorted(((i, s) for i, s in enumerate(kw) if s > 0), key=lambda x: -x[1]), 1)}
    v_rank: dict[int, int] = {}
    if qvec is not None:
        sims = [(i, cosine(qvec, d.vec)) for i, d in enumerate(docs) if d.vec is not None]
        v_rank = {i: r for r, (i, s) in enumerate(sorted((x for x in sims if x[1] >= min_vector), key=lambda x: -x[1]), 1)}
    hits = []
    for i, d in enumerate(docs):
        if i not in kw_rank and i not in v_rank:
            continue
        score = sum(1 / (rrf_k + r) for r in (kw_rank.get(i), v_rank.get(i)) if r)
        hits.append(Hit(d, score, v_rank.get(i), kw_rank.get(i)))
    return sorted(hits, key=lambda h: -h.score)[:k]
