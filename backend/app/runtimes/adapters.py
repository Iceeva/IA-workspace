"""Adaptateurs HTTP configurables pour les runtimes vocaux et image (§17, §18) : Phonon, Sana ou tout autre serveur.

Le protocole exact de ces moteurs n'est pas figé dans le code : on décrit leur API dans une configuration
(chemin, noms de champs, chemin de la réponse). Les valeurs par défaut suivent la convention OpenAI
(/v1/audio/transcriptions, /v1/images/generations), que de nombreux serveurs locaux imitent. Adaptez la
configuration à l'API réelle de votre moteur ; elle n'a pas été vérifiée contre Phonon ou Sana eux-mêmes."""
from __future__ import annotations
import base64
from dataclasses import dataclass, field
from typing import Awaitable, Callable

PostMultipart = Callable[[str, dict, dict, dict], Awaitable[dict]]   # url, headers, files, data → JSON
PostJson = Callable[[str, dict, dict], Awaitable[dict]]
Download = Callable[[str], Awaitable[bytes]]


class AdapterError(RuntimeError):
    pass


def dig(data, path: str):
    """Chemin pointé « data.0.b64_json » dans dicts/listes ; AdapterError si absent."""
    cur = data
    for part in path.split("."):
        try:
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise AdapterError(f"Champ « {path} » absent de la réponse du runtime") from e
    return cur


@dataclass
class SttSpec:
    path: str = "/v1/audio/transcriptions"
    file_field: str = "file"
    fields: dict = field(default_factory=lambda: {"model": "whisper-1"})
    language_field: str | None = "language"
    text_path: str = "text"


@dataclass
class ImageSpec:
    path: str = "/v1/images/generations"
    payload: dict = field(default_factory=lambda: {"prompt": "{prompt}", "n": 1, "size": "{size}", "response_format": "b64_json"})
    image_path: str = "data.0.b64_json"
    encoding: str = "base64"          # base64 | url


async def _httpx_multipart(url, headers, files, data):
    import httpx
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(url, headers=headers, files=files, data=data)
    if r.status_code >= 400:
        raise AdapterError(f"HTTP {r.status_code}")
    return r.json()


async def _httpx_json(url, headers, payload):
    import httpx
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        raise AdapterError(f"HTTP {r.status_code}")
    return r.json()


async def _httpx_get(url):
    import httpx
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as c:
        r = await c.get(url)
    if r.status_code >= 400:
        raise AdapterError(f"HTTP {r.status_code}")
    return r.content


class HttpRuntime:
    def __init__(self, base_url: str, *, stt: SttSpec | None = None, image: ImageSpec | None = None,
                 headers: dict | None = None, post_multipart: PostMultipart = _httpx_multipart,
                 post_json: PostJson = _httpx_json, download: Download = _httpx_get, max_audio_mb: int = 50):
        self.base, self.stt, self.image, self.headers = base_url.rstrip("/"), stt, image, headers or {}
        self._mp, self._js, self._dl, self.max_audio = post_multipart, post_json, download, max_audio_mb * 1024 * 1024

    async def transcribe(self, audio: bytes, filename: str = "audio.wav", language: str | None = None) -> str:
        if self.stt is None:
            raise AdapterError("Ce runtime n'est pas configuré pour la transcription")
        if not audio or len(audio) > self.max_audio:
            raise AdapterError("Audio vide ou trop volumineux")
        s = self.stt
        data = dict(s.fields)
        if language and s.language_field:
            data[s.language_field] = language
        resp = await self._mp(self.base + s.path, self.headers, {s.file_field: (filename, audio)}, data)
        text = dig(resp, s.text_path)
        if not isinstance(text, str):
            raise AdapterError("La transcription n'est pas du texte")
        return text.strip()

    async def generate_image(self, prompt: str, size: str = "1024x1024") -> bytes:
        if self.image is None:
            raise AdapterError("Ce runtime n'est pas configuré pour la génération d'images")
        if not prompt.strip() or len(prompt) > 4000:
            raise AdapterError("Prompt vide ou trop long")
        spec = self.image

        def fill(v):
            return v.replace("{prompt}", prompt).replace("{size}", size) if isinstance(v, str) else v
        resp = await self._js(self.base + spec.path, self.headers, {k: fill(v) for k, v in spec.payload.items()})
        raw = dig(resp, spec.image_path)
        if spec.encoding == "url":
            return await self._dl(str(raw))
        try:
            return base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as e:
            raise AdapterError("Image base64 invalide") from e
