from __future__ import annotations
import json
import os
from .base import LLMConfigError, LLMError, LLMProvider, LLMResponse, Message


async def _post(url: str, headers: dict, payload: dict, timeout: float = 120.0) -> dict:
    import httpx  # import tardif : le module reste importable sans httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


class _OpenAICompatible(LLMProvider):
    key_env: str | None = None

    def _base_url(self) -> str:
        return self.base_url  # type: ignore[attr-defined]

    def _key(self) -> str | None:
        if self.key_env is None:
            return None
        key = os.getenv(self.key_env)
        if not key:
            raise LLMConfigError(f"{self.key_env} est requis pour le provider '{self.name}'")
        return key

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        key = self._key()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = await _post(f"{self._base_url()}/chat/completions", headers, {
            "model": model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages]})
        try:
            usage = data.get("usage", {})
            return LLMResponse(data["choices"][0]["message"]["content"], model,
                               usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), data)
        except (KeyError, IndexError) as e:
            raise LLMError(f"Réponse inattendue du provider {self.name}") from e


    async def stream(self, messages, *, model, temperature=0.2, max_tokens=4096):
        import httpx
        key = self._key()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {"model": model, "temperature": temperature, "max_tokens": max_tokens, "stream": True,
                   "stream_options": {"include_usage": True},
                   "messages": [{"role": m.role, "content": m.content} for m in messages]}
        text, usage = [], {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self._base_url()}/chat/completions", headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    raise LLMError(f"HTTP {r.status_code}: {(await r.aread()).decode()[:300]}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line.endswith("[DONE]"):
                        continue
                    chunk = json.loads(line[6:])
                    usage = chunk.get("usage") or usage
                    for ch in chunk.get("choices", []):
                        delta = ch.get("delta", {}).get("content")
                        if delta:
                            text.append(delta)
                            yield delta
        yield LLMResponse("".join(text), model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


class OpenRouterProvider(_OpenAICompatible):
    name, base_url, key_env = "openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"


class OpenAIProvider(_OpenAICompatible):
    name, base_url, key_env = "openai", "https://api.openai.com/v1", "OPENAI_API_KEY"


class OllamaProvider(_OpenAICompatible):
    name = "ollama"

    def _base_url(self) -> str:
        url = os.getenv("OLLAMA_BASE_URL")
        if not url:
            raise LLMConfigError("OLLAMA_BASE_URL est requis pour le provider 'ollama'")
        return url.rstrip("/") + "/v1"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMConfigError("ANTHROPIC_API_KEY est requis pour le provider 'anthropic'")
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        data = await _post("https://api.anthropic.com/v1/messages",
                           {"x-api-key": key, "anthropic-version": "2023-06-01"},
                           {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                            "system": system,
                            "messages": [{"role": m.role, "content": m.content}
                                         for m in messages if m.role != "system"]})
        try:
            text = "".join(b["text"] for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise LLMError("Réponse inattendue du provider anthropic") from e
        u = data.get("usage", {})
        return LLMResponse(text, model, u.get("input_tokens", 0), u.get("output_tokens", 0), data)


_REGISTRY = {c.name: c for c in (OpenRouterProvider, OpenAIProvider, AnthropicProvider, OllamaProvider)}


def get_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("LLM_PROVIDER", "openrouter")).lower()
    if name not in _REGISTRY:
        raise LLMConfigError(f"Provider inconnu: {name}. Choix: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]()
