import asyncio

from app.llm.base import LLMError, LLMResponse
from app.routing.models import NoModelAvailable, RoutingPrefs
from app.services.runtime_factory import ProviderCfg, build_runtime

CFGS = [
    ProviderCfg("openai", "cloud", api_key="k", priority=1, models=[
        {"id": "big", "caps": ["chat", "code"], "quality": 0.9, "cost_in": 5, "cost_out": 15, "context": 100000}]),
    ProviderCfg("ollama", "local", priority=2, local=True, models=[
        {"id": "qwen", "caps": ["chat", "code"], "quality": 0.5}]),
    ProviderCfg("ollama", "off", enabled=False, models=[{"id": "x"}]),
]


def test_no_enabled_provider_gives_none():
    assert build_runtime([]) is None and build_runtime([ProviderCfg("ollama", "a", enabled=False)]) is None


def test_registry_built_from_configs_and_disabled_ignored():
    rt = build_runtime(CFGS)
    assert sorted(m.key for m in rt.registry.all()) == ["cloud:big", "local:qwen"]
    assert rt.registry.get("local:qwen").local and not rt.registry.get("cloud:big").local


def test_resolution_of_route_keys():
    rt = build_runtime(CFGS, RoutingPrefs(fallback=["local:qwen"]))
    assert [t.key for t in rt.provider.resolve("cloud:big")] == ["cloud:big", "local:qwen"]
    assert [t.key for t in rt.provider.resolve("auto:chat,code")][0] in ("cloud:big", "local:qwen")
    raw = rt.provider.resolve("some/legacy-model")
    assert [t.key for t in raw] == ["cloud:some/legacy-model"]            # fournisseur de plus petite priorité
    try:
        rt.provider.resolve("auto:vision"); assert False
    except NoModelAvailable:
        pass


def test_route_keys_per_role():
    rt = build_runtime(CFGS)
    assert rt.route_key("coder") == "auto:chat,code" and rt.route_key("reviewer", "auto") == "auto:chat"
    assert rt.route_key("coder", "cloud:big") == "cloud:big"            # choix explicite de l'agent respecté
    manual = build_runtime(CFGS, RoutingPrefs(mode="single", single="cloud:big"))
    assert manual.route_key("coder") == "cloud:big"
    per = build_runtime(CFGS, RoutingPrefs(mode="per_agent", per_agent={"coder": "local:qwen"}, single="cloud:big"))
    assert per.route_key("coder") == "local:qwen" and per.route_key("planner") == "cloud:big"
    strict = build_runtime(CFGS, RoutingPrefs(local_only=True))
    assert strict.route_key("coder").startswith("auto:")
    assert [t.key for t in strict.provider.resolve("auto:chat,code")] == ["local:qwen"]   # le cloud n'est jamais tenté
    try:
        build_runtime([CFGS[0]], RoutingPrefs(local_only=True)).route_key("coder"); assert False
    except NoModelAvailable:
        pass


def test_end_to_end_fallback_when_cloud_fails():
    rt = build_runtime(CFGS, RoutingPrefs(fallback=["local:qwen"]))
    class Boom:  name = "b"
    async def fail(*a, **k): raise LLMError("HTTP 500")
    async def ok(*a, **k): return LLMResponse("local answer", "qwen", 1, 1)
    rt.providers["cloud"].chat = fail
    rt.providers["local"].chat = ok
    r = asyncio.run(rt.provider.chat([], model="cloud:big"))
    assert r.content == "local answer"
