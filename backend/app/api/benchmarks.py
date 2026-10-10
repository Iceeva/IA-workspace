"""Benchmarks de modèles (§31) et recommandation selon le matériel (§32)."""
from __future__ import annotations
import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.db import get_db
from app.llm.providers import build_provider
from app.models.entities import Role
from app.runtimes import hardware as H
from app.runtimes.benchmark import BASIC_SUITE, run_benchmark
from app.services import assembly as A
from .common import ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["benchmarks"])
_SEM = asyncio.Semaphore(2)   # un benchmark appelle réellement le modèle (coût, charge) : concurrence bornée


class BenchIn(BaseModel):
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=200)
    runs: int = Field(3, ge=1, le=8)
    quality: bool = True
    max_tokens: int = Field(128, ge=16, le=512)


@router.post("/benchmarks")
async def benchmark(b: BenchIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    """Mesure TTFT, débit, stabilité et qualité d'un modèle d'un fournisseur configuré. Réservé aux administrateurs
    (les appels à un fournisseur cloud sont facturés). Les ressources système ne sont pas mesurées ici : le serveur
    n'est pas la machine de l'utilisateur — le bridge local expose son propre profil matériel."""
    c.require(Role.ADMIN)
    from app.api.bridge import get_broker
    cfgs, _, _ = await A.load_providers(db, c.org_id, c.user.id, get_broker())
    cfg = next((x for x in cfgs if x.name == b.provider), None)
    if cfg is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Fournisseur introuvable ou désactivé")
    if b.model not in {m["id"] for m in cfg.models}:
        raise AppError(422, "UNKNOWN_MODEL", "Ce modèle n'est pas déclaré pour ce fournisseur")
    prov = build_provider(cfg.kind, cfg.base_url, cfg.api_key, cfg.options)
    async with _SEM:
        rep = await run_benchmark(prov, b.model, runs=b.runs, max_tokens=b.max_tokens, quality=BASIC_SUITE if b.quality else None)
    return ok({**rep.to_dict(), "provider": b.provider, "model": b.model})


class ProfileIn(BaseModel):
    profile: dict
    ctx_len: int = Field(4096, ge=128, le=1_000_000)


@router.post("/hardware/recommend")
async def recommend(b: ProfileIn, c: Ctx = Depends(ctx)):
    """Reçoit le profil relevé par le Local Bridge (GET /hardware) et indique quels modèles conviennent."""
    p = H.profile_from_dict(b.profile)
    return ok({"profile": p.to_dict(), "models": H.recommend_models(p, b.ctx_len)})


# ---- pièces jointes multimodales (§16-§18) ---------------------------------------------------------------------------------
from fastapi import File, Form, UploadFile  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.pipelines import multimodal as MM  # noqa: E402
from app.routing.models import NoModelAvailable  # noqa: E402
from app.services.runtime_factory import build_runtime, prefs_from_settings  # noqa: E402


@router.post("/multimodal/prepare")
async def prepare(text: str = Form(""), files: list[UploadFile] = File(default_factory=list), c: Ctx = Depends(ctx),
                  db: AsyncSession = Depends(get_db)):
    """Transforme voix et images en texte exploitable par l'orchestrateur : micro → STT → mission, image → vision → mission.
    La transcription utilise le runtime configuré (STT_URL : Phonon ou serveur compatible) ; l'image, le modèle « vision » choisi par le routeur."""
    from app.api.bridge import get_broker
    from app.runtimes.adapters import PHONON_AUDIO_EXT, AdapterError, HttpRuntime, SttSpec
    from app.services.urlcheck import validate_provider_url
    c.require(Role.MEMBER)
    blobs = []
    for f in files[:MM.MAX_ATTACHMENTS + 1]:
        data = await f.read(MM.V.MAX_VIDEO_BYTES + 1)
        if len(data) > MM.V.MAX_VIDEO_BYTES:
            raise AppError(413, "ATTACHMENT_TOO_LARGE", "Pièce jointe trop volumineuse (64 Mo maximum)")
        blobs.append((f.filename or "fichier", data))
    st = get_settings()
    transcribe = None
    if st.stt_url:
        validate_provider_url(st.stt_url, allow_private=True)   # URL fixée par l'opérateur, pas par l'utilisateur
        rt = HttpRuntime(st.stt_url, stt=SttSpec.phonon(st.stt_model),
                         headers={"Authorization": f"Bearer {st.stt_api_key}"} if st.stt_api_key else {})
        async def transcribe(audio, name):
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in PHONON_AUDIO_EXT:       # Phonon refuse mp3/m4a/webm : conversion locale en WAV
                try:
                    audio, name = await MM.V.to_wav(audio), "audio.wav"
                except MM.V.VideoError as e:
                    raise MM.MultimodalError(str(e))
            try:
                return await rt.transcribe(audio, name)
            except AdapterError as e:
                raise MM.MultimodalError(f"Transcription impossible : {e}")
    cfgs, _, settings = await A.load_providers(db, c.org_id, c.user.id, get_broker())
    runtime = build_runtime(cfgs, prefs_from_settings(settings))
    describe = None
    if runtime is not None:
        try:
            route = runtime.route_key("vision", None, False, {"vision"})
        except NoModelAvailable:
            route = None
        if route:
            async def describe(img, question): return await MM.describe_image(runtime.provider, route, img, question)
    try:
        prep = await MM.prepare_mission(text, blobs, transcribe=transcribe, describe=describe)
    except MM.MultimodalError as e:
        raise AppError(422, "MULTIMODAL_ERROR", str(e))
    return ok({"mission": prep.mission, "attachments": prep.notes})


from pydantic import BaseModel, Field  # noqa: E402
from fastapi.responses import Response  # noqa: E402


class VideoGen(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    seconds: int = Field(default=5, ge=1, le=30)


@router.post("/multimodal/generate-video")
async def generate_video(body: VideoGen, c: Ctx = Depends(ctx)):
    """Texte → vidéo via le runtime configuré par l'opérateur (VIDEO_GEN_URL : Sana vidéo ou serveur compatible)."""
    from app.runtimes.adapters import AdapterError, HttpRuntime, VideoSpec
    from app.services.urlcheck import validate_provider_url
    c.require(Role.MEMBER)
    st = get_settings()
    if not st.video_gen_url:
        raise AppError(503, "VIDEO_UNAVAILABLE", "Aucun runtime de génération vidéo n'est configuré (VIDEO_GEN_URL)")
    validate_provider_url(st.video_gen_url, allow_private=True)
    try:
        data = await HttpRuntime(st.video_gen_url, video=VideoSpec()).generate_video(body.prompt, body.seconds)
    except AdapterError as e:
        raise AppError(502, "VIDEO_FAILED", str(e))
    return Response(data, media_type="video/webm" if data[:4] == b"\x1a\x45\xdf\xa3" else "video/mp4")
