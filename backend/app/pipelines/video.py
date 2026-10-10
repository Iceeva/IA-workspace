"""Vidéo (§16) : analyse = images clés (ffmpeg) + piste audio (ffmpeg → STT). La vidéo est une entrée non fiable :
conteneur reconnu aux octets magiques, ffmpeg limité aux protocoles `file`/`pipe` (pas de playlist qui lirait le réseau),
exécuté sans shell, avec délai, dans un répertoire temporaire détruit ensuite."""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import tempfile

MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_DURATION_S = 15 * 60
MAX_FRAMES = 12
DEFAULT_FRAMES = 6
FF_TIMEOUT_S = 120
_SAFE = ["-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe"]   # communs à ffmpeg et ffprobe


class VideoError(ValueError):
    pass


def sniff_video(data: bytes) -> str:
    """'mp4' (MP4/MOV/M4V) | 'webm' (WebM/Matroska) | 'avi' ; VideoError sinon."""
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "avi"
    raise VideoError("Format vidéo non reconnu (MP4/MOV, WebM/MKV ou AVI)")


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


async def _run(*args: str, timeout: float = FF_TIMEOUT_S) -> bytes:
    if not ffmpeg_available():
        raise VideoError("ffmpeg n'est pas installé : l'analyse vidéo est indisponible")
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        raise VideoError("Traitement vidéo trop long")
    if p.returncode != 0:
        raise VideoError("Vidéo illisible ou corrompue")
    return out


async def probe(path: str) -> dict:
    out = await _run("ffprobe", *_SAFE, "-print_format", "json", "-show_format", "-show_streams", path)
    try:
        j = json.loads(out)
        kinds = {s.get("codec_type") for s in j.get("streams", [])}
        dur = float(j.get("format", {}).get("duration") or 0)
    except (ValueError, TypeError) as e:
        raise VideoError("Métadonnées vidéo illisibles") from e
    return {"duration": dur, "video": "video" in kinds, "audio": "audio" in kinds}


def frame_times(duration: float, n: int) -> list[float]:
    """n instants répartis au milieu de n tranches égales (évite le noir du premier et du dernier fotogramme)."""
    n = max(1, min(n, MAX_FRAMES))
    if duration <= 0:
        return [0.0]
    return [round(duration * (i + 0.5) / n, 3) for i in range(n)]


async def extract(data: bytes, *, frames: int = DEFAULT_FRAMES) -> dict:
    """→ {"duration", "frames": [jpeg bytes], "audio": wav 16 kHz mono bytes | None}."""
    sniff_video(data)
    if not data or len(data) > MAX_VIDEO_BYTES:
        raise VideoError("Vidéo vide ou supérieure à 64 Mo")
    d = tempfile.mkdtemp(prefix="aiw-video-")
    try:
        src = os.path.join(d, "in.bin")
        with open(src, "wb") as f:
            f.write(data)
        info = await probe(src)
        if info["duration"] > MAX_DURATION_S:
            raise VideoError("Vidéo trop longue (15 minutes maximum)")
        if not info["video"] and not info["audio"]:
            raise VideoError("Aucune piste exploitable dans cette vidéo")
        imgs: list[bytes] = []
        if info["video"]:
            for i, t in enumerate(frame_times(info["duration"], frames)):
                dst = os.path.join(d, f"f{i}.jpg")
                await _run("ffmpeg", "-nostdin", *_SAFE, "-ss", str(t), "-i", src, "-frames:v", "1", "-vf", "scale='min(768,iw)':-2", "-q:v", "4", "-y", dst)
                if os.path.exists(dst):
                    with open(dst, "rb") as f:
                        imgs.append(f.read())
        wav = None
        if info["audio"]:
            dst = os.path.join(d, "a.wav")
            await _run("ffmpeg", "-nostdin", *_SAFE, "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-t", str(MAX_DURATION_S), "-y", dst)
            with open(dst, "rb") as f:
                wav = f.read()
        return {"duration": info["duration"], "frames": imgs, "audio": wav}
    finally:
        shutil.rmtree(d, ignore_errors=True)
