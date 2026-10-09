"""Points d'entrée du mode « pull » : le Local Bridge de l'utilisateur interroge ces routes (authentification X-API-Key)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.bridge.broker import JobBroker, MemoryBroker, RedisBroker
from app.core.errors import AppError
from .common import ok
from .deps import Ctx, ctx

router = APIRouter(prefix="/api/bridge", tags=["bridge"])
_broker: JobBroker | None = None


def get_broker() -> JobBroker:
    """Redis si disponible (plusieurs processus), sinon courtier mémoire (développement mono-processus)."""
    global _broker
    if _broker is None:
        try:
            from app.services.queue import client
            _broker = RedisBroker(client())
        except Exception:  # noqa: BLE001
            _broker = MemoryBroker()
    return _broker


def scope_of(c: Ctx) -> str:
    return f"{c.org_id}:{c.user.id}"


class PollIn(BaseModel):
    models: list[str] = Field(default_factory=list, max_length=200)
    runtimes: list[str] = Field(default_factory=list, max_length=20)
    version: str = Field("", max_length=20)
    wait_s: int = Field(20, ge=1, le=25)


class ResultIn(BaseModel):
    ok: bool
    content: str = Field("", max_length=400_000)
    prompt_tokens: int = Field(0, ge=0, le=10_000_000)
    completion_tokens: int = Field(0, ge=0, le=10_000_000)
    error: str = Field("", max_length=1000)


@router.post("/poll")
async def poll(b: PollIn, c: Ctx = Depends(ctx)):
    """Long-polling : signale que le bridge est en ligne (avec ses modèles) puis attend une tâche."""
    broker, scope = get_broker(), scope_of(c)
    await broker.heartbeat(scope, {"models": b.models, "runtimes": b.runtimes, "version": b.version})
    job = await broker.claim(scope, b.wait_s)
    return ok(job)


@router.post("/jobs/{job_id}/result")
async def result(job_id: str, b: ResultIn, c: Ctx = Depends(ctx)):
    if not await get_broker().complete(scope_of(c), job_id, b.model_dump()):
        raise AppError(404, "RESOURCE_NOT_FOUND", "Tâche inconnue, expirée ou déjà traitée")
    return ok({"accepted": True})


@router.get("/status")
async def status(c: Ctx = Depends(ctx)):
    info = await get_broker().status(scope_of(c))
    return ok({"online": info is not None, **(info or {})})
