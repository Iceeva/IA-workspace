import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, ai_platform, auth, chat, files, misc, resources, usage
from app.core import errors
from app.core.config import get_settings
from app.services.redis_utils import rate_limited
from app.utils.logging import setup_logging

setup_logging("api")
settings = get_settings()
app = FastAPI(title="AI Workspace API", version="0.2.0")
errors.install(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-API-Key"])
SECURE = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
          "Cross-Origin-Resource-Policy": "same-site", "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
          "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/auth/"):  # limiteur partagé via Redis, par IP
        ip = request.client.host if request.client else "?"
        if await rate_limited(f"auth:{ip}", settings.auth_rate_per_min):
            return JSONResponse({"success": False, "error": {"code": "RATE_LIMITED",
                                 "message": "Trop de tentatives, réessayez dans une minute"}}, status_code=429,
                                headers=SECURE)
    resp = await call_next(request)
    for k, v in SECURE.items():
        if not (path in ("/docs", "/redoc", "/openapi.json") and k == "Content-Security-Policy"):
            resp.headers.setdefault(k, v)
    if not path.startswith("/api/chat"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.get("/health")
async def health():
    return {"status": "ok"}


for r in (auth.router, resources.router, files.router, misc.router, usage.router, chat.router, admin.router, ai_platform.router):
    app.include_router(r)
