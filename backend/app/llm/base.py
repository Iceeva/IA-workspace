"""Abstraction des fournisseurs LLM. Aucune clé n'est jamais renvoyée au frontend."""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


class LLMConfigError(RuntimeError):
    """Clé API ou URL manquante pour le provider demandé."""


class LLMError(RuntimeError):
    """Erreur renvoyée par le provider (HTTP, quota, format)."""


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, messages: list[Message], *, model: str,
                   temperature: float = 0.2, max_tokens: int = 4096) -> LLMResponse: ...

    async def stream(self, messages: list[Message], *, model: str, temperature: float = 0.2,
                     max_tokens: int = 4096) -> AsyncIterator[str | LLMResponse]:
        """Produit des fragments de texte puis, en dernier, un LLMResponse (usage). Repli: une seule réponse."""
        r = await self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        yield r.content
        yield r
