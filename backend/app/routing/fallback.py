"""Fallback automatique entre fournisseurs (§40) avec disjoncteur simple."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, replace
from typing import Awaitable, Callable

from app.llm.base import LLMConfigError, LLMError, LLMProvider, LLMResponse

Emit = Callable[[str, dict], Awaitable[None]]
_TRANSIENT = (LLMError, LLMConfigError, asyncio.TimeoutError, OSError)


@dataclass(frozen=True)
class Target:
    provider: LLMProvider
    model: str
    key: str


class FallbackProvider(LLMProvider):
    """Essaie les cibles dans l'ordre. Le paramètre `model` des agents sert de clé de route :
    `resolve(model)` renvoie la chaîne ordonnée de cibles (voir ModelRouter.route(...).chain)."""
    name = "fallback"

    def __init__(self, resolve: Callable[[str], list[Target]], on_event: Emit | None = None,
                 cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.resolve, self.on_event, self.cooldown_s, self.clock = resolve, on_event, cooldown_s, clock
        self._down_until: dict[str, float] = {}

    def _cooling(self, key: str) -> bool:
        return self._down_until.get(key, 0.0) > self.clock()

    async def _emit(self, kind: str, data: dict) -> None:
        if self.on_event:
            await self.on_event(kind, data)

    def _order(self, targets: list[Target]) -> list[Target]:
        """Les cibles en pause passent après les autres mais restent un dernier recours."""
        return [t for t in targets if not self._cooling(t.key)] + [t for t in targets if self._cooling(t.key)]

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        targets = self.resolve(model)
        if not targets:
            raise LLMError(f"Aucune cible pour la route « {model} »")
        errors: list[str] = []
        for i, t in enumerate(self._order(targets)):
            try:
                r = await t.provider.chat(messages, model=t.model, temperature=temperature, max_tokens=max_tokens)
                self._down_until.pop(t.key, None)
                if errors:
                    await self._emit("model.fallback", {"used": t.key, "failed": errors})
                return replace(r, model=t.key)  # le modèle réellement utilisé, « fournisseur:modèle »
            except _TRANSIENT as e:
                self._down_until[t.key] = self.clock() + self.cooldown_s
                errors.append(f"{t.key}: {str(e)[:160]}")
                await self._emit("model.failed", {"target": t.key, "error": str(e)[:160], "attempt": i + 1})
        raise LLMError("Tous les fournisseurs ont échoué — " + " | ".join(errors))

    async def stream(self, messages, *, model, temperature=0.2, max_tokens=4096):
        targets = self.resolve(model)
        errors: list[str] = []
        for t in self._order(targets):
            started = False
            try:
                async for chunk in t.provider.stream(messages, model=t.model, temperature=temperature,
                                                     max_tokens=max_tokens):
                    started = True
                    yield chunk
                self._down_until.pop(t.key, None)
                if errors:
                    await self._emit("model.fallback", {"used": t.key, "failed": errors})
                return
            except _TRANSIENT as e:
                if started:  # du texte a déjà été émis : impossible de reprendre proprement
                    raise
                self._down_until[t.key] = self.clock() + self.cooldown_s
                errors.append(f"{t.key}: {str(e)[:160]}")
        raise LLMError("Tous les fournisseurs ont échoué — " + " | ".join(errors))
