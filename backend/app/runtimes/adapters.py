"""Adaptateurs HTTP configurables pour les runtimes vocaux et image/vidéo (§17, §18) : Phonon, Sana ou tout autre serveur.

L'API de chaque moteur est décrite par une configuration (chemin, champs, chemin de la réponse).
- Phonon : `SttSpec.phonon()` suit la documentation du serveur `fermion serve` (POST /v1/audio/transcriptions, requête
  multipart au format Whisper, modèle « phonon-2 », audio WAV/FLAC/OGG/AIFF, corps ≤ 32 Mo, `language` non implémenté,
  clé via `Authorization: Bearer`). Vérifié sur la documentation publiée, pas contre un serveur lancé ici.
- Sana : aucun serveur HTTP officiel n'existe (bibliothèque diffusers). `runtimes/servers/sana_server.py` en fournit un,
  qui expose `/v1/images/generations` et `/v1/videos/generations` : les défauts `ImageSpec`/`VideoSpec` y correspondent."""
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


PHONON_AUDIO_EXT = {".wav", ".flac", ".ogg", ".aiff", ".aif"}   # décodables par libsndfile ; mp3/m4a sont refusés par le serveur


@dataclass
class SttSpec:
    path: str = "/v1/audio/transcriptions"
    file_field: str = "file"
    fields: dict = field(default_factory=lambda: {"model": "phonon-2", "response_format": "json"})
    language_field: str | None = None     # Phonon : `language` accepté mais non implémenté → on ne l'envoie pas
    text_path: str = "text"
    accepted_ext: frozenset = frozenset(PHONON_AUDIO_EXT)   # autres formats : à convertir en WAV avant l'envoi
    max_mb: int = 32                      # plafond du corps de requête de `fermion serve`

    @classmethod
    def phonon(cls, model: str = "phonon-2") -> "SttSpec":
        return cls(fields={"model": model, "response_format": "json"})

    @classmethod
    def whisper(cls, model: str = "whisper-1") -> "SttSpec":
        """Serveur compatible Whisper/OpenAI : accepte aussi `language` et plus de formats."""
        return cls(fields={"model": model}, language_field="language", accepted_ext=frozenset(), max_mb=25)


@dataclass
class ImageSpec:
    path: str = "/v1/images/generations"
    payload: dict = field(default_factory=lambda: {"prompt": "{prompt}", "n": 1, "size": "{size}", "response_format": "b64_json"})
    image_path: str = "data.0.b64_json"
    encoding: str = "base64"          # base64 | url


@dataclass
class VideoSpec:
    """Génération texte → vidéo par POST JSON. Le défaut suit la même convention que ImageSpec ; à adapter par runtime."""
    path: str = "/v1/videos/generations"
    payload: dict = field(default_factory=lambda: {"prompt": "{prompt}", "duration": "{seconds}", "response_format": "b64_json"})
    video_path: str = "data.0.b64_json"
    encoding: str = "base64"          # base64 | url
    max_mb: int = 128


async def _httpx_multipart(url, headers, files, data):
    import httpx
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(url, headers=headers, files=files, data=data)
    if r.status_code >= 400:
        raise AdapterError(_http_error(r))
    return r.json()


def _http_error(r) -> str:
    """Message d'erreur du serveur (enveloppe OpenAI {"error": {"message"}}) tronqué, sinon le code HTTP."""
    try:
        m = r.json()["error"]["message"]
        return f"HTTP {r.status_code} : {str(m)[:200]}"
    except Exception:  # noqa: BLE001
        return f"HTTP {r.status_code}"


async def _httpx_json(url, headers, payload):
    import httpx
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        raise AdapterError(_http_error(r))
    return r.json()


async def _httpx_get(url):
    import httpx
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as c:
        r = await c.get(url)
    if r.status_code >= 400:
        raise AdapterError(f"HTTP {r.status_code}")
    return r.content


class HttpRuntime:
    def __init__(self, base_url: str, *, stt: SttSpec | None = None, image: ImageSpec | None = None, video: VideoSpec | None = None,
                 headers: dict | None = None, post_multipart: PostMultipart = _httpx_multipart,
                 post_json: PostJson = _httpx_json, download: Download = _httpx_get, max_audio_mb: int = 50):
        self.base, self.stt, self.image, self.video, self.headers = base_url.rstrip("/"), stt, image, video, headers or {}
        self._mp, self._js, self._dl, self.max_audio = post_multipart, post_json, download, max_audio_mb * 1024 * 1024

    async def transcribe(self, audio: bytes, filename: str = "audio.wav", language: str | None = None) -> str:
        if self.stt is None:
            raise AdapterError("Ce runtime n'est pas configuré pour la transcription")
        s = self.stt
        if not audio or len(audio) > min(self.max_audio, s.max_mb * 1024 * 1024):
            raise AdapterError(f"Audio vide ou supérieur à {s.max_mb} Mo")
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if s.accepted_ext and ext not in s.accepted_ext:
            raise AdapterError(f"Format « {ext or 'inconnu'} » non accepté par ce moteur : convertissez en WAV (16 kHz mono)")
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


    async def generate_video(self, prompt: str, seconds: int = 5) -> bytes:
        """Texte → vidéo. Le résultat est vérifié (conteneur reconnu, taille bornée) avant d'être rendu."""
        from app.pipelines.video import VideoError, sniff_video
        if self.video is None:
            raise AdapterError("Ce runtime n'est pas configuré pour la génération de vidéos")
        if not prompt.strip() or len(prompt) > 4000:
            raise AdapterError("Prompt vide ou trop long")
        if not 1 <= seconds <= 30:
            raise AdapterError("Durée demandée : 1 à 30 secondes")
        spec = self.video

        def fill(v):
            return v.replace("{prompt}", prompt).replace("{seconds}", str(seconds)) if isinstance(v, str) else v
        resp = await self._js(self.base + spec.path, self.headers, {k: fill(v) for k, v in spec.payload.items()})
        raw = dig(resp, spec.video_path)
        if spec.encoding == "url":
            data = await self._dl(str(raw))
        else:
            try:
                data = base64.b64decode(raw, validate=True)
            except (ValueError, TypeError) as e:
                raise AdapterError("Vidéo base64 invalide") from e
        if not data or len(data) > spec.max_mb * 1024 * 1024:
            raise AdapterError("Vidéo vide ou trop volumineuse")
        try:
            sniff_video(data)
        except VideoError as e:
            raise AdapterError("Le runtime n'a pas renvoyé une vidéo reconnue") from e
        return data
