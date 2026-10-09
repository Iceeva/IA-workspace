"""Catalogue d'agents, fournisseurs, routage de modèles, budget, outils, Quantization Studio."""
import re
import uuid
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import CryptoError, get_secretbox, mask
from app.core.db import get_db
from app.core.errors import AppError
from app.llm.providers import PRESETS
from app.models.entities import AiSettings, ProviderConfig, Role
from app.routing.models import NoModelAvailable
from app.routing.selector import AgentSelector
from app.services.assembly import get_org_catalog
from app.runtimes import quantization
from app.services.audit import audit
from app.services.runtime_factory import ProviderCfg, prefs_from_settings, registry_from_configs
from app.services.urlcheck import validate_provider_url
from app.tools.builtin import default_registry
from .common import ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["platform"])
KINDS = set(PRESETS) | {"anthropic"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,59}$")  # sert de préfixe de clé de modèle : pas de « : »


# ---- catalogue --------------------------------------------------------------------------------------------------
@router.get("/catalog/categories")
async def categories(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    return ok([{"name": n, "count": k} for n, k in (await get_org_catalog(db, c.org_id)).categories().items()])


@router.get("/catalog/agents")
async def search_agents(q: str = Query("", max_length=200), category: str | None = None, skill: str | None = None,
                        need: str | None = None, modality: str | None = None, role_kind: str | None = None,
                        local_only: bool = False, cloud_only: bool = False, sensitive: bool | None = None,
                        max_tokens: int | None = Query(None, ge=1), limit: int = Query(30, ge=1, le=100),
                        offset: int = Query(0, ge=0), c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    items, total = (await get_org_catalog(db, c.org_id)).search(q, category=category, skill=skill, need=need, modality=modality,
                                  role_kind=role_kind, local_only=local_only, cloud_only=cloud_only,
                                  sensitive=sensitive, max_tokens=max_tokens, limit=limit, offset=offset)
    return ok([a.to_dict() for a in items], total=total, limit=limit, offset=offset)


@router.get("/catalog/agents/{agent_id}")
async def get_agent(agent_id: str, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    a = (await get_org_catalog(db, c.org_id)).get(agent_id)
    if not a:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Agent introuvable")
    return ok(a.to_dict())


class SelectIn(BaseModel):
    mission: str = Field(min_length=1, max_length=20000)
    max_agents: int = Field(6, ge=1, le=12)


@router.post("/catalog/select")
async def select_agents(b: SelectIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Aperçu de la sélection d'agents pour une mission (heuristique locale, aucun appel de modèle)."""
    s = AgentSelector(await get_org_catalog(db, c.org_id)).select(b.mission, max_agents=b.max_agents)
    return ok({"agents": [{"id": p.agent.id, "name": p.agent.name, "score": p.score, "reason": p.reason,
                           "needs": list(p.agent.needs), "sensitive": p.agent.sensitive} for p in s.picks],
               "considered": s.considered, "catalog_size": s.catalog_size, "needs": sorted(s.needs),
               "sensitive": s.sensitive, "roles": sorted(s.intent.roles)})


# ---- outils, quantification -------------------------------------------------------------------------------------
@router.get("/tools")
async def tools(c: Ctx = Depends(ctx)):
    return ok([t.to_dict() for t in default_registry(".").all()])


@router.get("/quantization/compare")
async def quant_compare(params_b: float = Query(..., gt=0, le=2000), ctx_len: int = Query(4096, ge=128, le=1_000_000),
                        vram_gb: float | None = Query(None, ge=0), ram_gb: float | None = Query(None, ge=0),
                        c: Ctx = Depends(ctx)):
    rows = quantization.compare(params_b, ctx_len, vram_gb=vram_gb, ram_gb=ram_gb)
    best = quantization.best_fit(rows)
    return ok([r.to_dict() for r in rows], best=best.fmt if best else None,
              note="Quantification = compression AVEC perte ; valeurs indicatives, à confirmer par benchmark.")


# ---- fournisseurs -------------------------------------------------------------------------------------------------
class ModelIn(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    caps: list[str] = Field(default_factory=lambda: ["chat"], max_length=20)
    quality: float = Field(0.5, ge=0, le=1)
    speed: float = Field(0.5, ge=0, le=1)
    cost_in: float = Field(0, ge=0, le=10000)
    cost_out: float = Field(0, ge=0, le=10000)
    context: int = Field(8192, ge=1, le=10_000_000)
    local: bool | None = None


class ProviderIn(BaseModel):
    kind: str
    name: str
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    models: list[ModelIn] = Field(default_factory=list, max_length=200)
    enabled: bool = True
    priority: int = Field(100, ge=0, le=10000)
    local: bool = False
    options: dict[str, str] = Field(default_factory=dict, max_length=5)   # api_version (Azure), region (Bedrock)

    @field_validator("options")
    @classmethod
    def _opts(cls, v):
        if set(v) - {"api_version", "region"} or any(len(x) > 60 for x in v.values()):
            raise ValueError("options autorisées : api_version, region (60 caractères max)")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in KINDS:
            raise ValueError(f"Type inconnu. Types : {', '.join(sorted(KINDS))}")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not NAME_RE.match(v):
            raise ValueError("Nom : 2 à 60 caractères a-z, 0-9, - ou _ (sans « : »)")
        return v


class ProviderPatch(BaseModel):
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)  # "" supprime la clé
    models: list[ModelIn] | None = Field(None, max_length=200)
    enabled: bool | None = None
    priority: int | None = Field(None, ge=0, le=10000)
    local: bool | None = None
    options: dict[str, str] | None = None


def _check_url(kind: str, url: str | None) -> str | None:
    if url in (None, ""):
        return None
    try:
        return validate_provider_url(url, allow_private=get_settings().allow_private_provider_urls)
    except ValueError as e:
        raise AppError(422, "INVALID_PROVIDER_URL", str(e))


def _view(p: ProviderConfig) -> dict:
    hint = ""
    if p.api_key_enc:
        try:
            hint = mask(get_secretbox().decrypt(p.api_key_enc, aad=str(p.organization_id)))
        except CryptoError:
            hint = "illisible"  # clé de chiffrement changée : l'utilisateur doit ressaisir la clé API
    return {"id": str(p.id), "kind": p.kind, "name": p.name, "base_url": p.base_url, "has_key": bool(p.api_key_enc),
            "key_hint": hint, "models": p.models, "enabled": p.enabled, "priority": p.priority, "local": p.local,
            "options": p.options or {}}


def _need_key(kind: str, key: str | None, enc: str | None) -> None:
    if PRESETS.get(kind, {}).get("needs_key", kind == "anthropic") and not (key or enc):
        raise AppError(422, "API_KEY_REQUIRED", f"Une clé API est requise pour « {kind} »")


async def _provider(db, org, pid) -> ProviderConfig:
    p = (await db.execute(select(ProviderConfig).where(ProviderConfig.id == pid,
                                                       ProviderConfig.organization_id == org))).scalar_one_or_none()
    if not p:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Fournisseur introuvable")
    return p


@router.get("/providers/presets")
async def presets(c: Ctx = Depends(ctx)):
    return ok([{"kind": k, **v} for k, v in PRESETS.items()] + [{"kind": "anthropic", "base_url": "", "needs_key": True}])


@router.get("/providers")
async def list_providers(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.organization_id == c.org_id)
                             .order_by(ProviderConfig.priority, ProviderConfig.name))).scalars().all()
    return ok([_view(p) for p in rows])


@router.post("/providers", status_code=201)
async def create_provider(b: ProviderIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    _need_key(b.kind, b.api_key, None)
    dup = (await db.execute(select(ProviderConfig.id).where(ProviderConfig.organization_id == c.org_id,
                                                            ProviderConfig.name == b.name))).first()
    if dup:
        raise AppError(409, "PROVIDER_EXISTS", "Un fournisseur porte déjà ce nom")
    p = ProviderConfig(organization_id=c.org_id, kind=b.kind, name=b.name, base_url=_check_url(b.kind, b.base_url),
                       models=[m.model_dump() for m in b.models], enabled=b.enabled, priority=b.priority,
                       local=b.local, options=b.options)
    if b.api_key:
        p.api_key_enc = get_secretbox().encrypt(b.api_key, aad=str(c.org_id))
    db.add(p); await db.flush()
    await audit(db, "provider.create", user_id=c.user.id, org_id=c.org_id, resource="provider", resource_id=p.id,
                request=request, meta={"kind": b.kind, "name": b.name})  # jamais la clé
    await db.commit()
    return ok(_view(p))


@router.patch("/providers/{pid}")
async def update_provider(pid: uuid.UUID, b: ProviderPatch, request: Request, c: Ctx = Depends(ctx),
                          db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    p = await _provider(db, c.org_id, pid)
    data = b.model_dump(exclude_unset=True)
    if "base_url" in data:
        p.base_url = _check_url(p.kind, data["base_url"])
    if "api_key" in data:
        p.api_key_enc = get_secretbox().encrypt(data["api_key"], aad=str(c.org_id)) if data["api_key"] else None
    for k in ("enabled", "priority", "local"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if b.models is not None:
        p.models = [m.model_dump() for m in b.models]
    if b.options is not None:
        p.options = b.options
    _need_key(p.kind, None, p.api_key_enc)
    await audit(db, "provider.update", user_id=c.user.id, org_id=c.org_id, resource="provider", resource_id=p.id,
                request=request, meta={"fields": sorted(data)})
    await db.commit()
    return ok(_view(p))


@router.delete("/providers/{pid}")
async def delete_provider(pid: uuid.UUID, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    p = await _provider(db, c.org_id, pid)
    await audit(db, "provider.delete", user_id=c.user.id, org_id=c.org_id, resource="provider", resource_id=p.id,
                request=request, meta={"name": p.name})
    await db.delete(p); await db.commit()
    return ok({"deleted": True})


# ---- préférences de routage / confidentialité / budget ------------------------------------------------------------
class AiSettingsIn(BaseModel):
    mode: str = Field("auto", pattern="^(single|per_agent|auto)$")
    single_model: str | None = Field(None, max_length=160)
    per_agent: dict[str, str] = Field(default_factory=dict, max_length=100)
    weights: dict[str, float] = Field(default_factory=lambda: {"quality": 0.5, "speed": 0.2, "cost": 0.3})
    local_only: bool = False
    sensitive_local: bool = False
    prefer_local: bool = False
    max_blended_cost: float | None = Field(None, ge=0)
    fallback: list[str] = Field(default_factory=list, max_length=10)
    monthly_budget_usd: float | None = Field(None, ge=0)
    on_limit: str = Field("block", pattern="^(block|confirm)$")
    embedding_provider: str | None = Field(None, max_length=60)   # nom d'un fournisseur ; vide = embeddings lexicaux locaux
    embedding_model: str | None = Field(None, max_length=160)

    @field_validator("weights")
    @classmethod
    def _w(cls, v):
        if set(v) - {"quality", "speed", "cost"} or any(x < 0 for x in v.values()):
            raise ValueError("weights : clés quality/speed/cost, valeurs ≥ 0")
        return v


def _settings_view(s: AiSettings | None) -> dict:
    d = AiSettingsIn().model_dump()
    if s:
        d = {k: getattr(s, k) for k in d}
    return d


@router.get("/ai-settings")
async def get_ai_settings(c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    s = (await db.execute(select(AiSettings).where(AiSettings.organization_id == c.org_id))).scalar_one_or_none()
    return ok(_settings_view(s))


@router.put("/ai-settings")
async def put_ai_settings(b: AiSettingsIn, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.ADMIN)
    if b.mode == "single" and not b.single_model:
        raise AppError(422, "SINGLE_MODEL_REQUIRED", "Le mode « un seul modèle » exige single_model")
    s = (await db.execute(select(AiSettings).where(AiSettings.organization_id == c.org_id))).scalar_one_or_none()
    if s is None:
        s = AiSettings(organization_id=c.org_id); db.add(s)
    for k, v in b.model_dump().items():
        setattr(s, k, v)
    await audit(db, "ai_settings.update", user_id=c.user.id, org_id=c.org_id, resource="ai_settings",
                resource_id=c.org_id, request=request, meta={"mode": b.mode, "budget": b.monthly_budget_usd})
    await db.commit()
    return ok(_settings_view(s))


class RouteIn(BaseModel):
    needs: list[str] = Field(default_factory=lambda: ["chat"], max_length=20)
    agent_id: str | None = Field(None, max_length=80)
    sensitive: bool = False
    context: int = Field(0, ge=0, le=10_000_000)


@router.post("/models/route")
async def route_preview(b: RouteIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Quel modèle serait choisi, avec la chaîne de repli et la raison (aucun appel de modèle)."""
    from app.routing.models import ModelRouter
    rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.organization_id == c.org_id,
                                                          ProviderConfig.enabled.is_(True)))).scalars().all()
    cfgs = [ProviderCfg(p.kind, p.name, models=p.models, local=p.local or p.kind == "bridge") for p in rows]
    s = (await db.execute(select(AiSettings).where(AiSettings.organization_id == c.org_id))).scalar_one_or_none()
    try:
        d = ModelRouter(registry_from_configs(cfgs)).route(set(b.needs), prefs_from_settings(s), agent_id=b.agent_id,
                                                           needed_context=b.context, sensitive=b.sensitive)
    except NoModelAvailable as e:
        raise AppError(422, "NO_MODEL_AVAILABLE", str(e))
    return ok(d.to_dict())
