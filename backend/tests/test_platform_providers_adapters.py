import asyncio
import base64

from app.llm import providers as P
from app.llm.base import LLMConfigError, LLMError, Message
from app.runtimes.adapters import AdapterError, HttpRuntime, ImageSpec, SttSpec, dig


def run(c): return asyncio.run(c)


def test_azure_url_header_and_response():
    seen = {}
    async def fake_post(url, headers, payload, timeout=120.0):
        seen.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "salut"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    orig, P._post = P._post, fake_post
    try:
        az = P.build_provider("azure", "https://res.openai.azure.com/", "AZKEY", {"api_version": "2025-01-01"})
        r = run(az.chat([Message("user", "hi")], model="mon dep/1"))
    finally:
        P._post = orig
    assert seen["url"] == "https://res.openai.azure.com/openai/deployments/mon%20dep%2F1/chat/completions?api-version=2025-01-01"
    assert seen["headers"] == {"api-key": "AZKEY"} and r.content == "salut" and (r.prompt_tokens, r.completion_tokens) == (3, 2)
    for bad in (lambda: P.build_provider("azure", None, "k"), lambda: P.build_provider("azure", "https://x", None)):
        try:
            bad(); assert False
        except LLMConfigError:
            pass


def test_bedrock_converse_mapping_usage_and_errors():
    msgs = [Message("system", "règle"), Message("assistant", "intro"), Message("user", "a"), Message("user", "b")]
    system, conv = P.BedrockProvider.to_converse(msgs)
    assert system == [{"text": "règle"}] and conv[0]["role"] == "user" and conv[1]["role"] == "assistant"
    assert conv[2]["content"][0]["text"] == "a\n\nb" and [c["role"] for c in conv] == ["user", "assistant", "user"]

    class Client:
        def converse(self, **kw):
            self.kw = kw
            if kw["modelId"] == "bad":
                raise RuntimeError("AccessDenied")
            return {"output": {"message": {"content": [{"text": "bon"}, {"text": "jour"}]}}, "usage": {"inputTokens": 7, "outputTokens": 4}}
    c = Client(); bp = P.BedrockProvider("us-east-1", client=c)
    r = run(bp.chat([Message("system", "s"), Message("user", "hi")], model="anthropic.x", temperature=0.1, max_tokens=50))
    assert r.content == "bonjour" and (r.prompt_tokens, r.completion_tokens) == (7, 4)
    assert c.kw["inferenceConfig"] == {"maxTokens": 50, "temperature": 0.1} and c.kw["system"] == [{"text": "s"}]
    try:
        run(bp.chat([Message("user", "x")], model="bad")); assert False
    except LLMError as e:
        assert "AccessDenied" in str(e)
    try:
        P.build_provider("bedrock"); assert False
    except LLMConfigError:
        pass
    assert isinstance(P.build_provider("bedrock", None, None, {"region": "eu-west-1"}), P.BedrockProvider)
    try:
        P.BedrockProvider("r", "seulement-une-partie")._get_client(); assert False
    except LLMConfigError:
        pass


def test_dig_paths():
    assert dig({"a": [{"b": 5}]}, "a.0.b") == 5
    for bad in ("a.1", "x", "a.0.z"):
        try:
            dig({"a": [{"b": 5}]}, bad); assert False
        except AdapterError:
            pass


def test_stt_adapter_default_openai_convention_and_custom_mapping():
    calls = []
    async def mp(url, headers, files, data):
        calls.append((url, headers, files, data)); return {"result": {"transcript": " bonjour le monde "}}
    rt = HttpRuntime("http://127.0.0.1:9001/", stt=SttSpec(path="/transcribe", file_field="audio", fields={"fast": "1"},
                                                          language_field="lang", text_path="result.transcript"),
                     headers={"X-K": "v"}, post_multipart=mp)
    assert run(rt.transcribe(b"RIFFdata", "m.wav", "fr")) == "bonjour le monde"
    url, headers, files, data = calls[0]
    assert url == "http://127.0.0.1:9001/transcribe" and files == {"audio": ("m.wav", b"RIFFdata")} and data == {"fast": "1", "lang": "fr"}
    for bad in (b"", b"x" * (2 * 1024 * 1024)):
        try:
            run(HttpRuntime("http://x", stt=SttSpec(), post_multipart=mp, max_audio_mb=1).transcribe(bad)); assert False
        except AdapterError:
            pass
    try:
        run(HttpRuntime("http://x").transcribe(b"a")); assert False
    except AdapterError:
        pass


def test_image_adapter_base64_and_url_modes():
    png = b"\x89PNG fake"
    sent = []
    async def js(url, headers, payload):
        sent.append((url, payload)); return {"data": [{"b64_json": base64.b64encode(png).decode(), "url": "http://img/1"}]}
    rt = HttpRuntime("http://127.0.0.1:9000", image=ImageSpec(), post_json=js)
    assert run(rt.generate_image("un chat", "512x512")) == png
    assert sent[0][1] == {"prompt": "un chat", "n": 1, "size": "512x512", "response_format": "b64_json"}
    async def dl(url): return b"downloaded:" + url.encode()
    rt2 = HttpRuntime("http://x", image=ImageSpec(image_path="data.0.url", encoding="url"), post_json=js, download=dl)
    assert run(rt2.generate_image("x")) == b"downloaded:http://img/1"
    async def bad_js(url, headers, payload): return {"data": [{"b64_json": "!!pas du base64!!"}]}
    for rt3, prompt in ((HttpRuntime("http://x", image=ImageSpec(), post_json=bad_js), "p"), (rt, " "), (rt, "x" * 5000)):
        try:
            run(rt3.generate_image(prompt)); assert False
        except AdapterError:
            pass


def test_phonon_spec_follows_documented_server_api():
    """fermion serve : multipart Whisper, modèle phonon-2, WAV/FLAC/OGG/AIFF, 32 Mo, `language` non envoyé."""
    calls = []
    async def mp(url, headers, files, data):
        calls.append((url, headers, files, data)); return {"text": " salut "}
    rt = HttpRuntime("http://127.0.0.1:8000", stt=SttSpec.phonon(), headers={"Authorization": "Bearer k"}, post_multipart=mp)
    assert run(rt.transcribe(b"RIFFdata", "a.wav", "fr")) == "salut"
    url, headers, files, data = calls[0]
    assert url == "http://127.0.0.1:8000/v1/audio/transcriptions" and files == {"file": ("a.wav", b"RIFFdata")}
    assert data == {"model": "phonon-2", "response_format": "json"} and headers["Authorization"] == "Bearer k"
    for name in ("a.mp3", "a.m4a", "noext"):             # refusés par le serveur : l'adaptateur le dit avant l'envoi
        try:
            run(rt.transcribe(b"x", name)); assert False
        except AdapterError as e:
            assert "WAV" in str(e)
    try:
        run(rt.transcribe(b"x" * (33 * 1024 * 1024), "big.wav")); assert False
    except AdapterError:
        pass
    w = SttSpec.whisper()
    assert w.language_field == "language" and not w.accepted_ext and w.fields == {"model": "whisper-1"}


def test_sana_server_helpers():
    from app.runtimes.servers.sana_server import parse_size, video_frames
    assert parse_size("1024x768") == (1024, 768) and parse_size("100x99999") == (256, 2048) and parse_size("1000x1000") == (992, 992)
    for bad in ("big", "10", "axb"):
        try:
            parse_size(bad); assert False
        except ValueError:
            pass
    assert video_frames(5) == 81 and video_frames(1) == 17 and video_frames(999) == video_frames(10) == 161
