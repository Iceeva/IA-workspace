"""Sélection des agents (§4) : ne retient que les agents pertinents, un seul par sujet et par rôle."""
from __future__ import annotations
from dataclasses import dataclass, field

from app.catalog.catalog import Catalog
from app.catalog.model import AgentDef
from .intent import Intent, IntentAnalyzer

_PRIMARY = {"build", "specialist"}


@dataclass
class Pick:
    agent: AgentDef
    score: float
    matched: tuple[str, ...]
    reason: str


@dataclass
class Selection:
    intent: Intent
    picks: list[Pick] = field(default_factory=list)
    considered: int = 0       # agents qui avaient au moins une correspondance
    catalog_size: int = 0     # taille du catalogue : le reste n'est jamais chargé

    @property
    def agents(self) -> list[AgentDef]:
        return [p.agent for p in self.picks]

    @property
    def sensitive(self) -> bool:
        return any(p.agent.sensitive for p in self.picks)

    @property
    def needs(self) -> set[str]:
        return {n for p in self.picks for n in p.agent.needs}


class AgentSelector:
    def __init__(self, catalog: Catalog, analyzer: IntentAnalyzer | None = None):
        self.catalog, self.analyzer = catalog, analyzer or IntentAnalyzer()

    def select(self, mission: str, *, max_agents: int = 6, relative_cutoff: float = 0.34,
               intent: Intent | None = None) -> Selection:
        intent = intent or self.analyzer.analyze(mission)
        sel = Selection(intent=intent, catalog_size=len(self.catalog))
        cands = self.catalog.candidates(intent.tokens)
        sel.considered = len(cands)
        eligible = []
        for a, hits, score in cands:
            if a.role_kind in _PRIMARY:
                eligible.append((a, hits, score))
            elif a.role_kind in intent.roles and not (intent.creation and a.role_kind == "test"):
                eligible.append((a, hits, score + 1))  # rôle explicitement demandé : léger avantage
        # un agent de rôle explicite remplace l'agent « build » du même sujet
        explicit_domains = {a.domain for a, _, _ in eligible if a.role_kind not in _PRIMARY}
        eligible = [e for e in eligible if e[0].role_kind not in _PRIMARY or e[0].domain not in explicit_domains]
        # un seul agent par (mots-clés touchés, groupe de rôle) : le plus couvrant, puis l'ordre du catalogue
        best: dict[tuple, tuple] = {}
        for a, hits, score in eligible:
            group = "primary" if a.role_kind in _PRIMARY else a.role_kind
            key = (hits, group)
            cur = best.get(key)
            if cur is None or (score, -self.catalog.order(a.id)) > (cur[2], -self.catalog.order(cur[0].id)):
                best[key] = (a, hits, score)
        ranked = sorted(best.values(), key=lambda e: (-e[2], self.catalog.order(e[0].id)))
        if ranked:
            floor = ranked[0][2] * relative_cutoff
            ranked = [e for e in ranked if e[2] >= floor][:max_agents]
        sel.picks = [Pick(a, round(s, 2), tuple(sorted(h)),
                          f"correspond à : {', '.join(sorted(h))} (rôle : {a.role_kind})") for a, h, s in ranked]
        return sel
