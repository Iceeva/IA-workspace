import asyncio

from app.bridge.broker import MemoryBroker
from app.bridge.provider import BridgeProvider
from app.llm.base import LLMError, Message
from app.llm.providers import build_provider
from app.routing.fallback import FallbackProvider, Target
from app.llm.base import LLMConfigError


def run(c): return asyncio.run(c)


def test_scope_isolation_and_job_ownership():
    async def go():
        b = MemoryBroker()
        jid = await b.submit("org1:alice", {"type": "chat"})
        assert await b.claim("org1:bob", 0.05) is None                    # Bob ne voit pas la file d'Alice
        job = await b.claim("org1:alice", 0.5)
        assert job["id"] == jid
        assert not await b.complete("org1:bob", jid, {"ok": True})        # Bob ne peut pas répondre
        assert await b.complete("org1:alice", jid, {"ok": True, "content": "x"})
        assert not await b.complete("org1:alice", jid, {"ok": True})      # une seule réponse
        assert (await b.wait_result(jid, 1))["content"] == "x"
        assert not await b.complete("org1:alice", "inconnu", {})
    run(go())


def test_heartbeat_expires_to_offline():
    async def go():
        t = [0.0]; b = MemoryBroker(clock=lambda: t[0])
        assert await b.status("s") is None
        await b.heartbeat("s", {"models": ["m"]}); assert (await b.status("s"))["models"] == ["m"]
        t[0] = 61; assert await b.status("s") is None
    run(go())


def test_provider_end_to_end_with_a_simulated_bridge():
    async def go():
        b = MemoryBroker(); p = BridgeProvider(b, "o:u", timeout_s=2)
        async def fake_bridge():
            await b.heartbeat("o:u", {"models": ["ollama:q"]})
            job = await b.claim("o:u", 1)
            assert job["type"] == "chat" and job["model"] == "ollama:q" and job["max_tokens"] == 8192
            await b.complete("o:u", job["id"], {"ok": True, "content": "local!", "prompt_tokens": 4, "completion_tokens": 2})
        t = asyncio.create_task(fake_bridge()); await asyncio.sleep(0.01)
        r = await p.chat([Message("user", "salut")], model="ollama:q", max_tokens=10 ** 6)
        await t
        assert (r.content, r.prompt_tokens, r.completion_tokens) == ("local!", 4, 2)
    run(go())


def test_provider_errors_offline_timeout_and_bridge_failure_trigger_fallback():
    async def go():
        b = MemoryBroker()
        off = BridgeProvider(b, "o:u", timeout_s=0.05)
        try:
            await off.chat([Message("user", "x")], model="m"); assert False
        except LLMError as e:
            assert "hors ligne" in str(e)
        await b.heartbeat("o:u", {})
        try:
            await off.chat([Message("user", "x")], model="m"); assert False                 # en ligne mais muet
        except LLMError as e:
            assert "à temps" in str(e)
        async def failing():
            job = await b.claim("o:u", 1)
            await b.complete("o:u", job["id"], {"ok": False, "error": "modèle introuvable"})
        t = asyncio.create_task(failing()); await asyncio.sleep(0.01)
        try:
            await BridgeProvider(b, "o:u", timeout_s=1).chat([Message("user", "x")], model="m"); assert False
        except LLMError as e:
            assert "introuvable" in str(e)
        await t
        # bridge hors ligne → le fallback bascule sur le fournisseur suivant
        class Cloud:
            name = "c"
            async def chat(self, messages, *, model, **k):
                from app.llm.base import LLMResponse
                return LLMResponse("cloud", model, 1, 1)
        fp = FallbackProvider(lambda m: [Target(BridgeProvider(MemoryBroker(), "z:z"), "m", "bridge:m"), Target(Cloud(), "big", "cloud:big")])
        r = await fp.chat([Message("user", "x")], model="r")
        assert r.content == "cloud" and r.model == "cloud:big"
    run(go())


def test_build_provider_bridge_requires_broker_and_scope():
    for opts in ({}, {"broker": MemoryBroker()}, {"scope": "a:b"}):
        try:
            build_provider("bridge", options=opts); assert False
        except LLMConfigError:
            pass
    assert isinstance(build_provider("bridge", options={"broker": MemoryBroker(), "scope": "a:b"}), BridgeProvider)
