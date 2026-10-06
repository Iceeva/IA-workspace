"""Model Registry + Model Router (§7, §9). Les agents déclarent des capacités ; le routeur choisit le modèle."""
from __future__ import annotations
from dataclasses import dataclass, field


class NoModelAvailable(RuntimeError):
    """Aucun modèle ne satisfait les exigences et la politique de confidentialité."""


@dataclass(frozen=True)
class ModelInfo:
    id: str                                   # identifiant chez le fournisseur
    provider: str                             # fournisseur configuré (ex. "openrouter", "ollama")
    caps: frozenset[str] = frozenset({"chat"})
    quality: float = 0.5                      # 0..1, saisi ou mesuré (benchmarks)
    speed: float = 0.5                        # 0..1
    cost_in: float = 0.0                      # USD / 1M tokens (0 pour un modèle local)
    cost_out: float = 0.0
    context: int = 8192
    local: bool = False
    modalities: frozenset[str] = frozenset({"text"})
    available: bool = True

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def blended_cost(self) -> float:
        return 0.75 * self.cost_in + 0.25 * self.cost_out

    def to_dict(self) -> dict:
        return {"key": self.key, "id": self.id, "provider": self.provider, "caps": sorted(self.caps),
                "quality": self.quality, "speed": self.speed, "cost_in": self.cost_in, "cost_out": self.cost_out,
                "context": self.context, "local": self.local, "modalities": sorted(self.modalities),
                "available": self.available}


class ModelRegistry:
    def __init__(self, models=()):
        self._m: dict[str, ModelInfo] = {}
        for m in models:
            self.add(m)

    def add(self, m: ModelInfo) -> None:
        self._m[m.key] = m

    def remove(self, key: str) -> None:
        self._m.pop(key, None)

    def get(self, key: str) -> ModelInfo | None:
        return self._m.get(key)

    def all(self) -> list[ModelInfo]:
        return list(self._m.values())

    def set_available(self, key: str, available: bool) -> None:
        if key in self._m:
            self._m[key] = ModelInfo(**{**self._m[key].__dict__, "available": available})

    def __len__(self) -> int:
        return len(self._m)


@dataclass
class RoutingPrefs:
    mode: str = "auto"                                   # single | per_agent | auto (§9)
    single: str | None = None                            # clé de modèle, mode « un seul modèle »
    per_agent: dict[str, str] = field(default_factory=dict)  # agent_id ou rôle → clé de modèle
    weights: dict[str, float] = field(default_factory=lambda: {"quality": 0.5, "speed": 0.2, "cost": 0.3})
    local_only: bool = False                             # confidentialité : rien ne quitte la machine
    sensitive_local: bool = False                        # agents sensibles → modèles locaux uniquement
    prefer_local: bool = False
    max_blended_cost: float | None = None                # plafond USD / 1M tokens
    fallback: list[str] = field(default_factory=list)    # ordre de repli configurable par l'utilisateur (§40)
    max_chain: int = 4


@dataclass
class RouteDecision:
    chosen: ModelInfo
    chain: list[ModelInfo]                               # chosen en tête, puis les replis
    reason: str                                          # « pourquoi ce modèle » (observabilité, §41)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"chosen": self.chosen.to_dict(), "chain": [m.key for m in self.chain], "reason": self.reason,
                "warnings": self.warnings}


class ModelRouter:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def route(self, needs, prefs: RoutingPrefs | None = None, *, agent_id: str | None = None,
              needed_context: int = 0, sensitive: bool = False) -> RouteDecision:
        prefs, needs = prefs or RoutingPrefs(), set(needs)
        force_local = prefs.local_only or (sensitive and prefs.sensitive_local)
        manual = self._manual_key(prefs, agent_id)
        if manual:
            return self._route_manual(manual, needs, prefs, needed_context, force_local)
        pool = self._eligible(needs, prefs, needed_context, force_local)
        if not pool:
            raise NoModelAvailable(self._explain_empty(needs, needed_context, force_local))
        ranked = self._rank(pool, prefs)
        chain = self._with_fallback(ranked[0], ranked, prefs, needs, needed_context, force_local)
        top = ranked[0]
        reason = (f"auto : {top.key} (qualité {top.quality:.2f}, vitesse {top.speed:.2f}, "
                  f"coût ≈ ${top.blended_cost:.2f}/M, {'local' if top.local else 'cloud'}) parmi {len(pool)} "
                  f"candidat(s) pour les capacités {sorted(needs) or ['chat']}")
        return RouteDecision(top, chain, reason)

    # -- internes ---------------------------------------------------------------------------------
    @staticmethod
    def _manual_key(prefs: RoutingPrefs, agent_id: str | None) -> str | None:
        if prefs.mode == "single" and prefs.single:
            return prefs.single
        if prefs.mode == "per_agent" and agent_id and agent_id in prefs.per_agent:
            return prefs.per_agent[agent_id]
        if prefs.mode == "per_agent" and prefs.single:   # agent non configuré : modèle par défaut s'il existe
            return prefs.single
        return None

    def _route_manual(self, key, needs, prefs, ctx, force_local) -> RouteDecision:
        m = self.registry.get(key)
        if m is None or not m.available:
            raise NoModelAvailable(f"Le modèle choisi « {key} » est inconnu ou indisponible")
        if force_local and not m.local:
            raise NoModelAvailable(f"« {key} » est un modèle cloud : refusé par la politique de confidentialité")
        warns = []
        if missing := needs - m.caps:
            warns.append(f"« {key} » ne déclare pas : {', '.join(sorted(missing))}")
        if ctx > m.context:
            warns.append(f"contexte requis ({ctx}) > contexte du modèle ({m.context})")
        chain = [m]
        for k in prefs.fallback:
            f = self.registry.get(k)
            if f and f.available and f.key != m.key and not (force_local and not f.local):
                chain.append(f)
        return RouteDecision(m, chain[:prefs.max_chain], f"manuel ({prefs.mode}) : {key}", warns)

    def _eligible(self, needs, prefs, ctx, force_local) -> list[ModelInfo]:
        out = []
        for m in self.registry.all():
            if not m.available or not needs <= m.caps or m.context < ctx:
                continue
            if force_local and not m.local:
                continue
            if prefs.max_blended_cost is not None and m.blended_cost > prefs.max_blended_cost:
                continue
            out.append(m)
        return out

    def _rank(self, pool: list[ModelInfo], prefs: RoutingPrefs) -> list[ModelInfo]:
        w = prefs.weights
        top_cost = max((m.blended_cost for m in pool), default=0.0)

        def score(m: ModelInfo) -> float:
            cost = (m.blended_cost / top_cost) if top_cost else 0.0
            return (w.get("quality", 0) * m.quality + w.get("speed", 0) * m.speed + w.get("cost", 0) * (1 - cost)
                    + (0.15 if prefs.prefer_local and m.local else 0.0))
        return sorted(pool, key=lambda m: (-score(m), m.key))

    def _with_fallback(self, top, ranked, prefs, needs, ctx, force_local) -> list[ModelInfo]:
        chain, seen = [top], {top.key}
        for k in prefs.fallback:                         # d'abord l'ordre voulu par l'utilisateur
            m = self.registry.get(k)
            if m and m.available and m.key not in seen and needs <= m.caps and not (force_local and not m.local):
                chain.append(m); seen.add(m.key)
        for m in ranked:
            if m.key not in seen:
                chain.append(m); seen.add(m.key)
        return chain[:prefs.max_chain]

    def _explain_empty(self, needs, ctx, force_local) -> str:
        have = len(self.registry.all())
        why = f"{have} modèle(s) enregistré(s) mais aucun ne fournit {sorted(needs)}"
        if ctx:
            why += f" avec un contexte ≥ {ctx}"
        if force_local:
            why += " en local (politique de confidentialité)"
        return why
