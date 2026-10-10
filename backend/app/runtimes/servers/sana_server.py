"""Serveur local Sana (images et vidéo) — sur la bibliothèque diffusers, car Sana n'a pas de serveur HTTP officiel.

Expose l'API attendue par `ImageSpec` / `VideoSpec` :
  POST /v1/images/generations  {"prompt", "size": "1024x1024", "n": 1, "response_format": "b64_json"} → {"data":[{"b64_json"}]}
  POST /v1/videos/generations  {"prompt", "duration": 5}                                              → {"data":[{"b64_json"}]} (MP4)
  GET  /health

Appels diffusers conformes à la documentation publiée : `SanaPipeline(prompt, height, width, guidance_scale=4.5,
num_inference_steps=20).images[0]` et `SanaVideoPipeline(prompt, negative_prompt, height=480, width=832, frames, guidance_scale=6,
num_inference_steps=50).frames[0]` + `export_to_video(fps=16)`. Transformer en bfloat16 ; encodeur de texte bfloat16 ; VAE vidéo float32.
NON EXÉCUTÉ dans l'environnement de développement (pas de GPU ni de poids) : à valider sur votre machine.

Installation : pip install fastapi uvicorn "diffusers>=0.36" transformers accelerate torch pillow
Lancement   : python -m app.runtimes.servers.sana_server --port 8020 [--api-key CLE] [--no-video]
Écoute sur 127.0.0.1 par défaut ; ne l'exposez pas sans clé API ni proxy TLS."""
from __future__ import annotations
import argparse
import asyncio
import base64
import hmac
import io
import os
import tempfile

IMAGE_MODEL = "Efficient-Large-Model/Sana_1600M_1024px_BF16_diffusers"
VIDEO_MODEL = "Efficient-Large-Model/SANA-Video_2B_480p_diffusers"
VIDEO_FPS = 16
MAX_SIDE, MIN_SIDE = 2048, 256
MAX_VIDEO_S = 10


def parse_size(size: str) -> tuple[int, int]:
    """« 1024x768 » → (largeur, hauteur) bornés et alignés sur 32 px (exigence des modèles Sana)."""
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except ValueError:
        raise ValueError("size attendu au format LARGEURxHAUTEUR")
    clamp = lambda v: max(MIN_SIDE, min(MAX_SIDE, v)) // 32 * 32
    return clamp(w), clamp(h)


def video_frames(seconds: int) -> int:
    """Nombre d'images pour `seconds` à 16 i/s : 4k+1 comme les 81 images par défaut (≈ 5 s), plafonné à 10 s."""
    return 4 * round(max(1, min(seconds, MAX_VIDEO_S)) * VIDEO_FPS / 4) + 1


def build_app(api_key: str = "", video: bool = True):
    import torch
    from diffusers import SanaPipeline
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field

    app = FastAPI(title="Sana local server")
    lock = asyncio.Lock()           # un calcul GPU à la fois
    state: dict = {}

    def auth(authorization: str = Header(default="")):
        if api_key and not hmac.compare_digest(authorization, f"Bearer {api_key}"):
            raise HTTPException(401, "Clé API invalide")

    def image_pipe():
        if "img" not in state:
            p = SanaPipeline.from_pretrained(os.getenv("SANA_IMAGE_MODEL", IMAGE_MODEL), torch_dtype=torch.float32)
            p.to("cuda")
            p.text_encoder.to(torch.bfloat16)
            p.transformer = p.transformer.to(torch.bfloat16)
            state["img"] = p
        return state["img"]

    def video_pipe():
        if "vid" not in state:
            from diffusers import SanaVideoPipeline
            p = SanaVideoPipeline.from_pretrained(os.getenv("SANA_VIDEO_MODEL", VIDEO_MODEL), dtype=torch.bfloat16)
            p.text_encoder.to(torch.bfloat16)
            p.vae.to(torch.float32)
            p.to("cuda")
            state["vid"] = p
        return state["vid"]

    class ImgReq(BaseModel):
        prompt: str = Field(min_length=1, max_length=4000)
        size: str = "1024x1024"
        n: int = Field(default=1, ge=1, le=1)
        response_format: str = "b64_json"

    class VidReq(BaseModel):
        prompt: str = Field(min_length=1, max_length=4000)
        duration: int | str = 5

    @app.get("/health")
    def health():
        return {"status": "ok", "image_model": IMAGE_MODEL, "video": video}

    @app.post("/v1/images/generations", dependencies=[Depends(auth)])
    async def images(req: ImgReq):
        if req.response_format != "b64_json":
            raise HTTPException(400, "Seul response_format=b64_json est pris en charge")
        try:
            w, h = parse_size(req.size)
        except ValueError as e:
            raise HTTPException(400, str(e))

        def run() -> bytes:
            img = image_pipe()(prompt=req.prompt, height=h, width=w, guidance_scale=4.5, num_inference_steps=20).images[0]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        async with lock:
            data = await asyncio.to_thread(run)
        return {"data": [{"b64_json": base64.b64encode(data).decode()}]}

    @app.post("/v1/videos/generations", dependencies=[Depends(auth)])
    async def videos(req: VidReq):
        if not video:
            raise HTTPException(404, "Génération vidéo désactivée (--no-video)")
        try:
            seconds = int(req.duration)
        except ValueError:
            raise HTTPException(400, "duration doit être un entier de secondes")

        def run() -> bytes:
            from diffusers.utils import export_to_video
            frames = video_pipe()(prompt=req.prompt + " motion score: 30.", negative_prompt="", height=480, width=832,
                                  frames=video_frames(seconds), guidance_scale=6, num_inference_steps=50).frames[0]
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "v.mp4")
                export_to_video(frames, out, fps=VIDEO_FPS)
                return open(out, "rb").read()
        async with lock:
            data = await asyncio.to_thread(run)
        return {"data": [{"b64_json": base64.b64encode(data).decode()}]}

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--api-key", default=os.getenv("SANA_API_KEY", ""))
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    import uvicorn
    uvicorn.run(build_app(a.api_key, not a.no_video), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
