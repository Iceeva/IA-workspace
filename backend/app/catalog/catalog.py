"""Catalogue d'agents : stockage, index inversé, recherche filtrée (Marketplace, §35)."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

from .model import AgentDef, Permission
from .taxonomy import build_default_catalog
from .text import tokens


def agent_from_dict(d: dict) -> AgentDef:
    """Construit une définition depuis un dict JSON (agents personnalisés, extensions du catalogue — §5, §36)."""
    for k in ("id", "name", "category"):
        if not d.get(k):
            raise ValueError(f"Champ obligatoire manquant: {k}")
    tools = d.get("tools", {})
    pairs = tuple((n, int(Permission[p] if isinstance(p, str) else p)) for n, p in
                  (tools.items() if isinstance(tools, dict) else tools))
    kws = tuple(sorted(set(tokens(" ".join([d["name"], *d.get("keywords", [])])))))
    return AgentDef(
        id=d["id"], name=d["name"], description=d.get("description", ""), category=d["category"],
        subcategory=d.get("subcategory", d["category"]), domain=d.get("domain", d["id"]),
        role_kind=d.get("role_kind", "specialist"), skills=tuple(d.get("skills", ())), keywords=kws,
        needs=tuple(d.get("needs", ("chat",))), tools=pairs, inputs=tuple(d.get("inputs", ("text",))),
        outputs=tuple(d.get("outputs", ("text",))),
        permission_level=int(max([p for _, p in pairs] or [int(Permission.READ)])),
        est_tokens=int(d.get("est_tokens", 4000)), min_ram_gb=float(d.get("min_ram_gb", 0)),
        needs_gpu=bool(d.get("needs_gpu", False)), local_ok=bool(d.get("local_ok", True)),
        cloud_ok=bool(d.get("cloud_ok", True)), sensitive=bool(d.get("sensitive", False)),
        system_prompt=d.get("system_prompt", f"Tu es {d['name']}."), source=d.get("source", "custom"))


class Catalog:
    def __init__(self, agents=()):
        self._agents: dict[str, AgentDef] = {}
        self._order: dict[str, int] = {}
        self._kw: dict[str, set[str]] = defaultdict(set)
        self._dt: dict[str, set[str]] = {}
        for a in agents:
            self.register(a)

    @classmethod
    def default(cls) -> "Catalog":
        return cls(build_default_catalog())

    def __len__(self) -> int:
        return len(self._agents)

    def __iter__(self):
        return iter(self._agents.values())

    def get(self, agent_id: str) -> AgentDef | None:
        return self._agents.get(agent_id)

    def register(self, agent: AgentDef) -> None:
        """Ajoute ou remplace un agent (même id) sans toucher au cœur du système."""
        if agent.id in self._agents:
            self._unindex(self._agents[agent.id])
        else:
            self._order[agent.id] = len(self._order)
        self._agents[agent.id] = agent
        for t in agent.keywords:
            self._kw[t].add(agent.id)
        self._dt[agent.id] = set(tokens(agent.description)) - set(agent.keywords)

    def _unindex(self, a: AgentDef) -> None:
        for ids in self._kw.values():
            ids.discard(a.id)

    def load_json(self, path: str | Path) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for d in data:
            self.register(agent_from_dict(d))
        return len(data)

    def categories(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for a in self._agents.values():
            out[a.category] += 1
        return dict(sorted(out.items()))

    def order(self, agent_id: str) -> int:
        return self._order[agent_id]

    def hits(self, agent: AgentDef, qtokens) -> tuple[frozenset[str], int]:
        """(mots-clés touchés, nombre de mots de description touchés)."""
        q = set(qtokens)
        kw = frozenset(q & set(agent.keywords))
        return kw, len(q & self._dt.get(agent.id, set()))

    def candidates(self, qtokens) -> list[tuple[AgentDef, frozenset[str], float]]:
        """Agents dont au moins un mot-clé correspond. Score = 3·mots-clés touchés + couverture (départage) + description."""
        ids: set[str] = set()
        for t in set(qtokens):
            ids |= self._kw.get(t, set())
        out = []
        for i in ids:
            a = self._agents[i]
            kw, d = self.hits(a, qtokens)
            coverage = len(kw) / max(1, len(a.keywords))
            out.append((a, kw, 3 * len(kw) + 0.5 * coverage + 0.2 * d))
        return out

    def search(self, query: str = "", *, category: str | None = None, skill: str | None = None,
               need: str | None = None, modality: str | None = None, role_kind: str | None = None,
               local_only: bool = False, cloud_only: bool = False, max_tokens: int | None = None,
               sensitive: bool | None = None, limit: int = 50, offset: int = 0) -> tuple[list[AgentDef], int]:
        """Recherche Marketplace. Retourne (page, total). Sans requête : tri par catégorie puis nom."""
        q = tokens(query)
        if q:
            ranked = sorted(self.candidates(q), key=lambda c: (-c[2], self._order[c[0].id]))
            pool = [a for a, _, _ in ranked]
        else:
            pool = sorted(self._agents.values(), key=lambda a: (a.category, a.name))

        def ok(a: AgentDef) -> bool:
            return ((category is None or a.category.lower() == category.lower())
                    and (skill is None or any(s == skill or s.startswith(skill + ".") for s in a.skills))
                    and (need is None or need in a.needs)
                    and (modality is None or modality in (*a.inputs, *a.outputs))
                    and (role_kind is None or a.role_kind == role_kind)
                    and (not local_only or a.local_ok) and (not cloud_only or a.cloud_ok)
                    and (max_tokens is None or a.est_tokens <= max_tokens)
                    and (sensitive is None or a.sensitive == sensitive))
        res = [a for a in pool if ok(a)]
        return res[offset:offset + limit], len(res)
