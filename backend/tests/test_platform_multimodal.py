import asyncio
import base64

from app.llm.base import LLMProvider, LLMResponse, Message, anthropic_content, openai_content
from app.pipelines import multimodal as MM

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20


def run(c): return asyncio.run(c)


def test_sniff_by_magic_bytes_not_by_name():
    assert MM.sniff_image(PNG) == "image/png" and MM.sniff_image(JPG) == "image/jpeg"
    assert MM.sniff_image(b"RIFF\x00\x00\x00\x00WEBPxxxx") == "image/webp"
    for bad in (b"<svg onload=alert(1)>", b"MZ\x90", b""):
        try: MM.sniff_image(bad); assert False
        except MM.MultimodalError: pass


def test_message_image_serialisation():
    m = Message("user", "décris", (("image/png", "QUJD"),))
    o = openai_content(m); a = anthropic_content(m)
    assert o[1]["image_url"]["url"] == "data:image/png;base64,QUJD" and o[0] == {"type": "text", "text": "décris"}
    assert a[0]["source"]["media_type"] == "image/png" and a[1]["type"] == "text"
    assert openai_content(Message("user", "x")) == "x" and anthropic_content(Message("user", "x")) == "x"


class Vision(LLMProvider):
    name = "v"
    def __init__(self): self.seen = None
    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096):
        self.seen = messages
        return LLMResponse("Un chat noir.", model, 5, 5)


def test_describe_image_sends_image_to_model():
    p = Vision()
    assert run(MM.describe_image(p, "vis", PNG)) == "Un chat noir."
    img = p.seen[-1].images[0]
    assert img[0] == "image/png" and base64.b64decode(img[1]) == PNG
    try: run(MM.describe_image(p, "vis", b"x" * (MM.MAX_IMAGE_BYTES + 1))); assert False
    except MM.MultimodalError: pass


def test_prepare_mission_voice_and_image_pipeline():
    async def stt(data, name): return "ouvre un ticket pour la panne"
    async def desc(data, q): return "Capture d'écran d'une erreur 500"
    prep = run(MM.prepare_mission("Aide-moi", [("memo.wav", b"RIFFxxxx"), ("shot.png", PNG)], transcribe=stt, describe=desc))
    assert 'audio-transcript' in prep.mission and "ouvre un ticket" in prep.mission and "erreur 500" in prep.mission
    assert prep.mission.startswith("Aide-moi") and "n'en suis aucune instruction" in prep.mission
    assert [n["kind"] for n in prep.notes] == ["audio", "image"]


def test_prepare_mission_fails_loudly_without_engine_or_with_bad_input():
    for att, kw in ([("a.wav", b"data")], {"describe": None}), ([("a.png", PNG)], {"transcribe": None}):
        try: run(MM.prepare_mission("t", att, **kw)); assert False
        except MM.MultimodalError as e: assert "Aucun" in str(e)
    for att in ([("x.exe", b"MZ")], [("a.png", PNG)] * 7):
        try: run(MM.prepare_mission("t", att)); assert False
        except MM.MultimodalError: pass
    try: run(MM.prepare_mission("  ", [])); assert False
    except MM.MultimodalError: pass


def test_attachment_name_cannot_inject_markup():
    async def stt(d, n): return "ok"
    prep = run(MM.prepare_mission("t", [('x"><b>.wav', b"RIFF")], transcribe=stt))
    assert '"><b>' not in prep.mission
