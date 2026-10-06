import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.models.entities import LLMModelConfig, LLMProviderConfig


async def ensure_provider_enabled(db: AsyncSession, provider: str | None = None, model: str | None = None) -> None:
    """Un provider/modèle absent de la table est considéré actif ; désactivé par un admin → refus."""
    name = (provider or os.getenv("LLM_PROVIDER", "openrouter")).lower()
    row = await db.get(LLMProviderConfig, name)
    if row and not row.enabled:
        raise AppError(503, "PROVIDER_DISABLED", f"Le provider '{name}' est désactivé par l'administrateur")
    if model:
        m = (await db.execute(select(LLMModelConfig).where(LLMModelConfig.provider == name,
                                                           LLMModelConfig.model_id == model))).scalar_one_or_none()
        if m and not m.enabled:
            raise AppError(503, "MODEL_DISABLED", f"Le modèle '{model}' est désactivé par l'administrateur")
