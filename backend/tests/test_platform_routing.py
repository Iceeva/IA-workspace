import asyncio

from app.llm.base import LLMConfigError, LLMError, LLMProvider, LLMResponse
from app.llm.providers import PRESETS, AnthropicProvider, GenericOpenAIProvider, build_provider
from app.routing.fallback import FallbackProvider, Target
from app.routing.models import ModelInfo, ModelRegistry, ModelRouter, NoModelAvailable, RoutingPrefs

F = frozenset
BIG = ModelInfo("big", "cloud", F({"chat", "code", "reasoning", "vision"}), quality=0.95, speed=0.3, cost_in=10,
                cost_out=30, context=200_000)
FAST = ModelInfo("fast", "cloud", F({"chat", "code"}), quality=0.6, speed=0.95, cost_in=0.2, cost_out=0.6,
                 context=32_000)
LOCAL = ModelInfo("qwen3-8b", "ollama", F({"chat", "code"}), quality=0.55, speed=0.5, context=16_000, local=True)
DOWN = ModelInfo("dead", "cloud", F({"chat", "code"}), quality=1.0, speed=1.0, available=False)


def router():
    return ModelRouter(ModelRegistry([BIG, FAST, LOCAL, DOWN]))


def test_auto_prefers_quality_or_cost_by_weights():
    q = router().route({"chat", "code"}, RoutingPrefs(weights={"quality": 1, "speed": 0, "cost": 0}))
    assert q.chosen.key == "cloud:big"
    c = router().route({"chat", "code"}, RoutingPrefs(weights={"quality": 0, "speed": 0, "cost": 1}))
    assert c.chosen.local and "auto" in c.reason and "candidat" in c.reason


def test_capabilities_and_context_filter_candidates():
    assert router().route({"chat", "vision"}).chosen.key == "cloud:big"
    assert router().route({"chat"}, needed_context=100_000).chosen.key == "cloud:big"
    try:
        router().route({"chat", "text-to-image"}); assert False
    except NoModelAvailable as e:
        assert "text-to-image" in str(e)


def test_unavailable_models_are_never_chosen():
    d = router().route({"chat"}, RoutingPrefs(weights={"quality": 1, "speed": 1, "cost": 0}))
    assert "cloud:dead" not in [m.key for m in d.chain]


def test_privacy_local_only_and_sensitive_local():
    d = router().route({"chat", "code"}, RoutingPrefs(local_only=True))
    assert d.chosen.local and all(m.local for m in d.chain)
    assert router().route({"chat", "code"}, RoutingPrefs(sensitive_local=True), sensitive=True).chosen.local
    q = RoutingPrefs(sensitive_local=True, weights={"quality": 1, "speed": 0, "cost": 0})
    assert router().route({"chat", "code"}, q, sensitive=False).chosen.key == "cloud:big"  # non sensible : libre
    try:
        router().route({"chat", "vision"}, RoutingPrefs(local_only=True)); assert False
    except NoModelAvailable as e:
        assert "local" in str(e)


def test_budget_ceiling_filters_expensive_models():
    d = router().route({"chat", "code"}, RoutingPrefs(max_blended_cost=1.0,
                                                      weights={"quality": 1, "speed": 0, "cost": 0}))
    assert d.chosen.key == "cloud:fast"


def test_single_model_mode_applies_to_every_agent_and_warns_on_missing_caps():
    p = RoutingPrefs(mode="single", single="cloud:fast", fallback=["ollama:qwen3-8b"])
    d = router().route({"chat", "vision"}, p, agent_id="anything")
    assert d.chosen.key == "cloud:fast" and d.warnings and d.chain[1].key == "ollama:qwen3-8b"


def test_per_agent_mode_with_default_and_privacy_enforced():
    p = RoutingPrefs(mode="per_agent", per_agent={"python-developer": "ollama:qwen3-8b",
                                                   "researcher": "cloud:big"}, single="cloud:fast")
    r = router()
    assert r.route({"chat"}, p, agent_id="python-developer").chosen.local
    assert r.route({"chat"}, p, agent_id="researcher").chosen.key == "cloud:big"
    assert r.route({"chat"}, p, agent_id="other").chosen.key == "cloud:fast"
    p.local_only = True
    try:
        r.route({"chat"}, p, agent_id="researcher"); assert False
    except NoModelAvailable:
        pass
    try:
        r.route({"chat"}, RoutingPrefs(mode="single", single="cloud:dead")); assert False
    except NoModelAvailable:
        pass


def test_fallback_chain_follows_user_order_then_ranking():
    d = router().route({"chat", "code"}, RoutingPrefs(fallback=["ollama:qwen3-8b"], max_chain=3,
                                                      weights={"quality": 1, "speed": 0, "cost": 0}))
    assert [m.key for m in d.chain] == ["cloud:big", "ollama:qwen3-8b", "cloud:fast"]


# -- FallbackProvider ------------------------------------------------------------------------------
class P(LLMProvider):
    def __init__(self, name, fail=None): self.name, self.fail, self.calls = name, fail, 0
    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096):
        self.calls += 1
        if self.fail: raise self.fail
        return LLMResponse(f"{self.name}:{model}", model, 1, 1)


def test_fallback_uses_next_provider_and_reports_events():
    a, b = P("a", LLMError("HTTP 503")), P("b")
    ev = []
    async def emit(k, d): ev.append((k, d))
    fp = FallbackProvider(lambda m: [Target(a, "m1", "a:m1"), Target(b, "m2", "b:m2")], emit)
    r = asyncio.run(fp.chat([], model="route"))
    assert r.content == "b:m2" and [k for k, _ in ev] == ["model.failed", "model.fallback"]
    assert "503" in ev[1][1]["failed"][0]


def test_missing_key_triggers_fallback_and_total_failure_is_explicit():
    a, b = P("a", LLMConfigError("clé absente")), P("b", LLMError("down"))
    fp = FallbackProvider(lambda m: [Target(a, "x", "a:x"), Target(b, "y", "b:y")])
    try:
        asyncio.run(fp.chat([], model="r")); assert False
    except LLMError as e:
        assert "a:x" in str(e) and "b:y" in str(e)


def test_circuit_breaker_skips_failed_provider_then_retries_after_cooldown():
    now = [0.0]
    a, b = P("a", LLMError("x")), P("b")
    fp = FallbackProvider(lambda m: [Target(a, "m", "a"), Target(b, "m", "b")], cooldown_s=30, clock=lambda: now[0])
    asyncio.run(fp.chat([], model="r")); asyncio.run(fp.chat([], model="r"))
    assert a.calls == 1 and b.calls == 2          # « a » mis en pause après son échec
    now[0] = 31; a.fail = None
    assert asyncio.run(fp.chat([], model="r")).content.startswith("a:")


def test_stream_falls_back_before_first_chunk():
    class S(LLMProvider):
        name = "s"
        async def chat(self, *a, **k): raise LLMError("no")
        async def stream(self, messages, *, model, **k):
            raise LLMError("no")
            yield
    ok = P("ok")
    fp = FallbackProvider(lambda m: [Target(S(), "m", "s"), Target(ok, "m", "ok")])
    async def go():
        return [c async for c in fp.stream([], model="r")]
    out = asyncio.run(go())
    assert out[0] == "ok:m"


def test_provider_presets_cover_requested_vendors_and_build_validates():
    for k in ("openai", "mistral", "deepseek", "xai", "groq", "together", "fireworks", "google", "cohere",
              "openrouter", "ollama", "lmstudio", "llamacpp", "localai", "vllm", "custom"):
        assert k in PRESETS
    assert isinstance(build_provider("ollama"), GenericOpenAIProvider)
    assert isinstance(build_provider("anthropic", api_key="k"), AnthropicProvider)
    for bad in (lambda: build_provider("mistral"), lambda: build_provider("custom"), lambda: build_provider("nope")):
        try:
            bad(); assert False
        except LLMConfigError:
            pass
    assert build_provider("custom", "http://x:9/v1/", None).base_url == "http://x:9/v1"
