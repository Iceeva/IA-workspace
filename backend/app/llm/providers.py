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

    def _chat_url(self, model: str) -> str:
        return f"{self._base_url()}/chat/completions"

    def _headers(self) -> dict:
        key = self._key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        headers = self._headers()
        data = await _post(self._chat_url(model), headers, {
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
        headers = self._headers()
        payload = {"model": model, "temperature": temperature, "max_tokens": max_tokens, "stream": True,
                   "stream_options": {"include_usage": True},
                   "messages": [{"role": m.role, "content": m.content} for m in messages]}
        text, usage = [], {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", self._chat_url(model), headers=headers, json=payload) as r:
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


class AzureOpenAIProvider(_OpenAICompatible):
    """Azure OpenAI : l'URL contient le *déploiement* (passé dans `model`), l'authentification est l'en-tête `api-key`."""

    def __init__(self, endpoint: str, api_key: str, api_version: str = "2024-10-21"):
        self.name, self.base_url, self._api_key, self.api_version = "azure", endpoint.rstrip("/"), api_key, api_version

    def _chat_url(self, model: str) -> str:
        from urllib.parse import quote
        return f"{self.base_url}/openai/deployments/{quote(model, safe='')}/chat/completions?api-version={self.api_version}"

    def _headers(self) -> dict:
        return {"api-key": self._api_key}


class BedrockProvider(LLMProvider):
    """AWS Bedrock via l'API Converse (même format pour tous les modèles compatibles). Le paquet boto3 est requis.
    `credentials` : « ACCESS_KEY:SECRET_KEY[:SESSION_TOKEN] » (ou None pour la chaîne d'identifiants AWS par défaut)."""
    name = "bedrock"

    def __init__(self, region: str, credentials: str | None = None, client=None):
        self.region, self.credentials, self._client = region, credentials, client

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as e:
                raise LLMConfigError("Le paquet boto3 est requis pour Bedrock") from e
            kw = {}
            if self.credentials:
                parts = self.credentials.split(":")
                if len(parts) < 2:
                    raise LLMConfigError("Identifiants Bedrock : ACCESS_KEY:SECRET_KEY[:SESSION_TOKEN]")
                kw = {"aws_access_key_id": parts[0], "aws_secret_access_key": parts[1],
                      **({"aws_session_token": parts[2]} if len(parts) > 2 else {})}
            self._client = boto3.client("bedrock-runtime", region_name=self.region, **kw)
        return self._client

    @staticmethod
    def to_converse(messages) -> tuple[list[dict], list[dict]]:
        """(system, messages) : Converse exige user/assistant en alternance en commençant par user."""
        system = [{"text": m.content} for m in messages if m.role == "system"]
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if out and out[-1]["role"] == m.role:
                out[-1]["content"][0]["text"] += "\n\n" + m.content
            else:
                out.append({"role": m.role, "content": [{"text": m.content}]})
        if not out or out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": [{"text": "(début de conversation)"}]})
        return system, out

    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096) -> LLMResponse:
        import asyncio
        client = self._get_client()
        system, msgs = self.to_converse(messages)
        kw = {"modelId": model, "messages": msgs, "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature}}
        if system:
            kw["system"] = system
        try:
            resp = await asyncio.to_thread(client.converse, **kw)
        except Exception as e:  # noqa: BLE001 — botocore lève des erreurs variées (ClientError, réseau…)
            raise LLMError(f"Bedrock : {str(e)[:300]}") from e
        try:
            text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
        except (KeyError, TypeError) as e:
            raise LLMError("Réponse Bedrock inattendue") from e
        u = resp.get("usage", {})
        return LLMResponse(text, model, u.get("inputTokens", 0), u.get("outputTokens", 0))


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
    "azure": {"base_url": "", "needs_key": True, "options": ["api_version"]},   # URL = https://<ressource>.openai.azure.com
    "bedrock": {"base_url": "", "needs_key": False, "options": ["region"]},     # identifiants optionnels (chaîne AWS)
}


def build_provider(kind: str, base_url: str | None = None, api_key: str | None = None,
                   options: dict | None = None) -> LLMProvider:
    """Instancie un fournisseur depuis sa configuration (clé déjà déchiffrée, jamais journalisée)."""
    options = options or {}
    if kind == "anthropic":
        return AnthropicProvider(api_key)
    if kind == "azure":
        if not base_url or not api_key:
            raise LLMConfigError("Azure OpenAI exige l'URL de la ressource et une clé API")
        return AzureOpenAIProvider(base_url, api_key, options.get("api_version") or "2024-10-21")
    if kind == "bedrock":
        if not options.get("region"):
            raise LLMConfigError("Bedrock exige l'option « region » (ex. us-east-1)")
        return BedrockProvider(options["region"], api_key)
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
