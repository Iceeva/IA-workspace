"""Fournisseur « bridge » : exécute les appels de chat sur les modèles locaux de l'utilisateur via son Local Bridge."""
from __future__ import annotations
from app.llm.base import LLMError, LLMProvider, LLMResponse
from .broker import BridgeTimeout, JobBroker

MAX_TOKENS_CAP = 8192


class BridgeProvider(LLMProvider):
    name = "bridge"

    def __init__(self, broker: JobBroker, scope: str, timeout_s: float = 300.0):
        self.broker, self.scope, self.timeout_s = broker, scope, timeout_s

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        if await self.broker.status(self.scope) is None:
            raise LLMError("Local Bridge hors ligne : lancez-le sur votre machine (voir docs/PLATFORM.md)")
        jid = await self.broker.submit(self.scope, {
            "type": "chat", "model": model, "temperature": temperature, "max_tokens": min(max_tokens, MAX_TOKENS_CAP),
            "messages": [{"role": m.role, "content": m.content} for m in messages]})
        try:
            res = await self.broker.wait_result(jid, self.timeout_s)
        except BridgeTimeout as e:
            raise LLMError(str(e)) from e
        if not res.get("ok"):
            raise LLMError(f"Local Bridge : {str(res.get('error', 'erreur inconnue'))[:300]}")
        return LLMResponse(str(res.get("content", "")), model, int(res.get("prompt_tokens", 0)),
                           int(res.get("completion_tokens", 0)))
