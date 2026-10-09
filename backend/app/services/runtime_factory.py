"""Assemble, pour une organisation, ses fournisseurs configurés, son routeur de modèles et un provider avec
fallback. Partie pure (testable sans base) : `build_runtime`. Le chargement depuis la base est dans le worker."""
from __future__ import annotations
from dataclasses import dataclass, field

from app.llm.providers import build_provider
from app.routing.fallback import Emit, FallbackProvider, Target
from app.routing.models import ModelInfo, ModelRegistry, ModelRouter, RoutingPrefs

ROLE_NEEDS = {"coder": {"chat", "code"}, "debugger": {"chat", "code"}, "tester": {"chat", "code"}}


@dataclass
class ProviderCfg:
    kind: str
    name: str                       # identifiant unique dans l'organisation (sert de préfixe de clé de modèle)
    base_url: str | None = None
    api_key: str | None = None      # déjà déchiffrée, uniquement en mémoire
    models: list[dict] = field(default_factory=list)
    enabled: bool = True
    priority: int = 100             # plus petit = essayé en premier pour les identifiants bruts
    local: bool = False
    options: dict = field(default_factory=dict)  # api_version (Azure), region (Bedrock)…


@dataclass
class Runtime:
    registry: ModelRegistry
    router: ModelRouter
    prefs: RoutingPrefs
    provider: FallbackProvider
    providers: dict

    def route_key(self, role: str, agent_model: str | None = None, sensitive: bool = False) -> str:
        """Clé de route pour un rôle. Un modèle explicitement choisi pour l'agent est respecté ; sinon la
        préférence de l'organisation s'applique (auto → chaîne classée avec repli ; single/per_agent → modèle fixé).
        Lève NoModelAvailable si la politique ne laisse aucun modèle possible."""
        if agent_model and self.registry.get(agent_model):
            return agent_model
        needs = ROLE_NEEDS.get(role, {"chat"})
        if self.prefs.mode == "auto":
            self.router.route(needs, self.prefs, agent_id=role, sensitive=sensitive)  # valide la faisabilité
            return "auto:" + ",".join(sorted(needs))
        return self.router.route(needs, self.prefs, agent_id=role, sensitive=sensitive).chosen.key


def _model(cfg: ProviderCfg, m: dict) -> ModelInfo:
    return ModelInfo(id=m["id"], provider=cfg.name, caps=frozenset(m.get("caps", ["chat"])),
                     quality=float(m.get("quality", 0.5)), speed=float(m.get("speed", 0.5)),
                     cost_in=float(m.get("cost_in", 0)), cost_out=float(m.get("cost_out", 0)),
                     context=int(m.get("context", 8192)), local=bool(m.get("local", cfg.local)),
                     modalities=frozenset(m.get("modalities", ["text"])))


def build_runtime(cfgs: list[ProviderCfg], prefs: RoutingPrefs | None = None, on_event: Emit | None = None) -> Runtime | None:
    cfgs = sorted((c for c in cfgs if c.enabled), key=lambda c: c.priority)
    if not cfgs:
        return None
    prefs = prefs or RoutingPrefs()
    providers = {c.name: build_provider(c.kind, c.base_url, c.api_key, c.options) for c in cfgs}
    registry = ModelRegistry(_model(c, m) for c in cfgs for m in c.models)
    router = ModelRouter(registry)

    def target(m: ModelInfo) -> Target:
        return Target(providers[m.provider], m.id, m.key)

    def resolve(key: str) -> list[Target]:
        if key.startswith("auto"):
            needs = set(key.partition(":")[2].split(",")) - {""} or {"chat"}
            return [target(m) for m in router.route(needs, prefs).chain]
        m = registry.get(key)
        if m:
            chain = [m] + [f for k in prefs.fallback if (f := registry.get(k)) and f.available and f.key != m.key]
            return [target(x) for x in chain[:prefs.max_chain]]
        first = cfgs[0].name  # identifiant brut (ancien format) : fournisseur prioritaire
        return [Target(providers[first], key, f"{first}:{key}")]
    return Runtime(registry, router, prefs, FallbackProvider(resolve, on_event), providers)


def registry_from_configs(cfgs: list[ProviderCfg]) -> ModelRegistry:
    """Registre de modèles sans instancier les fournisseurs (aperçu de routage, aucune clé nécessaire)."""
    return ModelRegistry(_model(c, m) for c in cfgs if c.enabled for m in c.models)


def prefs_from_settings(s) -> RoutingPrefs:
    """Ligne AiSettings (ou None) → RoutingPrefs."""
    if s is None:
        return RoutingPrefs()
    return RoutingPrefs(mode=s.mode, single=s.single_model, per_agent=dict(s.per_agent or {}),
                        weights=dict(s.weights or {}), local_only=s.local_only, sensitive_local=s.sensitive_local,
                        prefer_local=s.prefer_local, max_blended_cost=s.max_blended_cost,
                        fallback=list(s.fallback or []))
