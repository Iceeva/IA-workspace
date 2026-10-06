import os
os.environ.setdefault("JWT_SECRET", "t" * 40)
os.environ.setdefault("JWT_REFRESH_SECRET", "r" * 40)
import httpx
import pytest_asyncio


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "store"))
    from app.core import config, db
    config.get_settings.cache_clear()
    db._engine = db._maker = None
    from app.main import app
    from app.models.entities import Base
    db.session_maker()
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def no(*a, **k): return False
    async def noop(*a, **k): return None
    queued = []
    async def fake_enqueue(i): queued.append(i)
    monkeypatch.setattr("app.main.rate_limited", no)
    monkeypatch.setattr("app.api.deps.is_revoked", no)
    monkeypatch.setattr("app.services.redis_utils.is_revoked", no)
    monkeypatch.setattr("app.api.auth.revoke", noop)
    monkeypatch.setattr("app.api.resources.enqueue", fake_enqueue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.queued = queued
        yield c


async def signup(c, email, org="Lab"):
    r = await c.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "full_name": "T",
                                                 "organization_name": org})
    assert r.status_code == 201, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['data']['access_token']}", "X-Organization-Id": d["organization_id"]}
