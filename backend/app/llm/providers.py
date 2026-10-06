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

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        key = self._api_key or os.getenv("ANTHROPIC_API_KEY")
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


class GenericOpenAIProvider(_OpenAICompatible):
    """Tout serveur compatible OpenAI (Mistral, DeepSeek, xAI, Groq, Together, Fireworks, LM Studio, vLLM,
    llama.cpp server, LocalAI, Ollama…). L'URL et la clé viennent de la configuration, pas de l'environnement."""

    def __init__(self, name: str, base_url: str, api_key: str | None = None):
        self.name, self.base_url, self._api_key = name, base_url.rstrip("/"), api_key

    def _key(self) -> str | None:
        return self._api_key or None


# Points d'entrée par défaut, modifiables par l'utilisateur dans l'interface (vérifiez-les : ils évoluent).
PRESETS: dict[str, dict] = {
    "openai": {"base_url": "https://api.openai.com/v1", "needs_key": True},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "needs_key": True},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "needs_key": True},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "needs_key": True},
    "xai": {"base_url": "https://api.x.ai/v1", "needs_key": True},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "needs_key": True},
    "together": {"base_url": "https://api.together.xyz/v1", "needs_key": True},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1", "needs_key": True},
    "google": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "needs_key": True},
    "cohere": {"base_url": "https://api.cohere.ai/compatibility/v1", "needs_key": True},
    "ollama": {"base_url": "http://localhost:11434/v1", "needs_key": False},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "needs_key": False},
    "llamacpp": {"base_url": "http://localhost:8080/v1", "needs_key": False},
    "localai": {"base_url": "http://localhost:8080/v1", "needs_key": False},
    "vllm": {"base_url": "http://localhost:8000/v1", "needs_key": False},
    "custom": {"base_url": "", "needs_key": False},
}


def build_provider(kind: str, base_url: str | None = None, api_key: str | None = None) -> LLMProvider:
    """Instancie un fournisseur depuis sa configuration (clé déjà déchiffrée, jamais journalisée)."""
    if kind == "anthropic":
        return AnthropicProvider(api_key)
    preset = PRESETS.get(kind)
    if preset is None:
        raise LLMConfigError(f"Type de fournisseur inconnu: {kind}")
    url = base_url or preset["base_url"]
    if not url:
        raise LLMConfigError(f"Le fournisseur '{kind}' nécessite une URL (endpoint)")
    if preset["needs_key"] and not api_key:
        raise LLMConfigError(f"Une clé API est requise pour le fournisseur '{kind}'")
    return GenericOpenAIProvider(kind, url, api_key)


_REGISTRY = {c.name: c for c in (OpenRouterProvider, OpenAIProvider, AnthropicProvider, OllamaProvider)}


def get_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("LLM_PROVIDER", "openrouter")).lower()
    if name not in _REGISTRY:
        raise LLMConfigError(f"Provider inconnu: {name}. Choix: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]()
