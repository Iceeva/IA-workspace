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


# ---- vidéo ----------------------------------------------------------------------------------------------------------
import os
import subprocess
import tempfile

from app.pipelines import video as V
from app.runtimes.adapters import AdapterError, HttpRuntime, VideoSpec


def _mk_video(audio: bool) -> bytes:
    d = tempfile.mkdtemp()
    out = os.path.join(d, "v.mp4")
    cmd = ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", "-y", out], check=True)
    return open(out, "rb").read()


def test_video_sniff_and_kind():
    assert V.sniff_video(b"\x00\x00\x00\x18ftypmp42") == "mp4"
    assert V.sniff_video(b"\x1a\x45\xdf\xa3....") == "webm"
    try:
        V.sniff_video(b"#EXTM3U\nhttp://evil/x")      # une playlist HLS ne passe pas
        assert False
    except V.VideoError:
        pass
    assert MM.kind_of("clip.webm", b"\x1a\x45\xdf\xa3....") == "video"   # .webm n'est plus présumé audio


def test_frame_times_are_inside_the_clip():
    t = V.frame_times(10.0, 4)
    assert t == [1.25, 3.75, 6.25, 8.75] and V.frame_times(0, 3) == [0.0] and len(V.frame_times(10, 99)) == V.MAX_FRAMES


def test_extract_real_video_with_ffmpeg():
    if not V.ffmpeg_available():
        return
    r = asyncio.run(V.extract(_mk_video(True), frames=3))
    assert len(r["frames"]) == 3 and all(f[:3] == b"\xff\xd8\xff" for f in r["frames"])
    assert r["audio"][:4] == b"RIFF" and 2.5 < r["duration"] < 3.5
    assert asyncio.run(V.extract(_mk_video(False), frames=2))["audio"] is None


def test_extract_rejects_garbage():
    try:
        asyncio.run(V.extract(b"\x00\x00\x00\x18ftyp" + b"junk" * 50))
        assert False
    except V.VideoError:
        pass


def test_prepare_mission_with_video_uses_frames_and_transcript():
    async def extract(data): return {"duration": 4.0, "frames": [b"a", b"b"], "audio": b"RIFFwav"}
    async def describe(img, q): return "plan " + img.decode()
    async def transcribe(a, n): return "bonjour"
    p = asyncio.run(MM.prepare_mission("Résume", [("c.mp4", b"\x00\x00\x00\x18ftypmp42")], transcribe=transcribe, describe=describe, extract=extract))
    assert 'type="video-frame"' in p.mission and 't="1.0s"' in p.mission and "plan b" in p.mission
    assert 'type="video-transcript"' in p.mission and p.notes[0]["kind"] == "video"
    for kw in ({"transcribe": None, "describe": describe}, {"transcribe": transcribe, "describe": None}):
        try:
            asyncio.run(MM.prepare_mission("x", [("c.mp4", b"\x00\x00\x00\x18ftypmp42")], extract=extract, **kw))
            assert False
        except MM.MultimodalError:
            pass


def test_generate_video_adapter_validates_output():
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 20
    async def js(url, h, payload):
        assert payload["prompt"] == "un chat" and payload["duration"] == "5" and url.endswith("/v1/videos/generations")
        return {"data": [{"b64_json": base64.b64encode(mp4).decode()}]}
    rt = HttpRuntime("http://x", video=VideoSpec(), post_json=js)
    assert asyncio.run(rt.generate_video("un chat", 5)) == mp4
    async def bad(url, h, payload): return {"data": [{"b64_json": base64.b64encode(b"<html>").decode()}]}
    for r, sec in ((HttpRuntime("http://x", video=VideoSpec(), post_json=bad), 5), (rt, 99), (HttpRuntime("http://x"), 5)):
        try:
            asyncio.run(r.generate_video("p", sec))
            assert False
        except AdapterError:
            pass
