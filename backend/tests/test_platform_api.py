"""Tests d'API de la plateforme (catalogue, fournisseurs, routage, budget). Exécutés par `pytest` avec les dépendances
du projet installées ; non exécutables dans l'environnement où ils ont été écrits (pas de FastAPI)."""
import uuid

from sqlalchemy import select

from .conftest import signup
from .test_api import make_project

KEY = "sk-super-secret-1234567890abcdef"


async def test_catalog_search_select_and_categories(client):
    h = await signup(client, "a@x.io")
    r = (await client.get("/api/catalog/agents", params={"q": "python", "limit": 5}, headers=h)).json()
    assert r["total"] >= 6 and len(r["data"]) == 5 and r["data"][0]["domain"] == "python"
    cats = (await client.get("/api/catalog/categories", headers=h)).json()["data"]
    assert sum(c["count"] for c in cats) > 1000
    sel = (await client.post("/api/catalog/select", headers=h, json={
        "mission": "Créer une application React avec une API Python et PostgreSQL, sécurisée"})).json()["data"]
    names = [a["name"] for a in sel["agents"]]
    assert "React Developer" in names and "PostgreSQL Specialist" in names and sel["catalog_size"] > 1000
    assert (await client.get("/api/catalog/agents/unknown", headers=h)).status_code == 404
    assert (await client.get("/api/tools", headers=h)).status_code == 200
    q = (await client.get("/api/quantization/compare", params={"params_b": 8, "vram_gb": 8}, headers=h)).json()
    assert q["best"] and q["data"][0]["kind"] == "lossy"


async def test_provider_key_is_encrypted_masked_and_never_returned(client, monkeypatch):
    monkeypatch.setattr("app.api.ai_platform.validate_provider_url", lambda u, **k: u.rstrip("/"))
    h = await signup(client, "a@x.io")
    r = await client.post("/api/providers", headers=h, json={
        "kind": "mistral", "name": "mistral-main", "api_key": KEY,
        "models": [{"id": "mistral-large", "caps": ["chat", "code"], "quality": 0.9, "cost_in": 2, "cost_out": 6}]})
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert KEY not in r.text and body["has_key"] and body["key_hint"] == "••••cdef"
    listing = await client.get("/api/providers", headers=h)
    assert KEY not in listing.text and "api_key" not in listing.text.replace("has_key", "")
    from app.core import db
    from app.models.entities import ProviderConfig
    async with db.session_maker()() as s:
        row = (await s.execute(select(ProviderConfig))).scalar_one()
        assert row.api_key_enc.startswith("enc:v1:") and KEY not in row.api_key_enc
    pid = body["id"]
    up = await client.patch(f"/api/providers/{pid}", headers=h, json={"enabled": False})
    assert up.json()["data"]["enabled"] is False and up.json()["data"]["has_key"]
    assert (await client.delete(f"/api/providers/{pid}", headers=h)).status_code == 200
    assert (await client.get("/api/providers", headers=h)).json()["data"] == []


async def test_provider_validation_and_tenant_isolation(client, monkeypatch):
    monkeypatch.setattr("app.api.ai_platform.validate_provider_url", lambda u, **k: u.rstrip("/"))
    a, b = await signup(client, "a@x.io", "A"), await signup(client, "b@x.io", "B")
    ok = {"kind": "ollama", "name": "local-ollama", "local": True}
    assert (await client.post("/api/providers", headers=a, json=ok)).status_code == 201
    assert (await client.post("/api/providers", headers=a, json=ok)).status_code == 409           # nom unique
    r = await client.post("/api/providers", headers=a, json={"kind": "openai", "name": "oa"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "API_KEY_REQUIRED"
    for bad in ({"kind": "nope", "name": "xx"}, {"kind": "ollama", "name": "Bad:Name"},
                {"kind": "ollama", "name": "okname", "models": [{"id": "m", "quality": 3}]}):
        assert (await client.post("/api/providers", headers=a, json=bad)).status_code == 422
    assert (await client.get("/api/providers", headers=b)).json()["data"] == []
    pid = (await client.get("/api/providers", headers=a)).json()["data"][0]["id"]
    assert (await client.patch(f"/api/providers/{pid}", headers=b, json={"enabled": False})).status_code == 404
    assert (await client.delete(f"/api/providers/{pid}", headers=b)).status_code == 404


async def test_private_provider_url_is_refused_by_default(client):
    h = await signup(client, "a@x.io")
    r = await client.post("/api/providers", headers=h, json={"kind": "custom", "name": "meta",
                                                            "base_url": "http://169.254.169.254/v1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PROVIDER_URL"


async def test_ai_settings_and_route_preview(client, monkeypatch):
    monkeypatch.setattr("app.api.ai_platform.validate_provider_url", lambda u, **k: u.rstrip("/"))
    h = await signup(client, "a@x.io")
    await client.post("/api/providers", headers=h, json={"kind": "ollama", "name": "local", "local": True,
                      "models": [{"id": "qwen", "caps": ["chat", "code"], "quality": 0.5}]})
    await client.post("/api/providers", headers=h, json={"kind": "mistral", "name": "cloud", "api_key": KEY,
                      "models": [{"id": "big", "caps": ["chat", "code"], "quality": 0.95, "cost_in": 5, "cost_out": 15}]})
    d = (await client.post("/api/models/route", headers=h, json={"needs": ["chat", "code"]})).json()["data"]
    assert d["chosen"]["key"] in ("cloud:big", "local:qwen") and "auto" in d["reason"]
    put = await client.put("/api/ai-settings", headers=h, json={"mode": "auto", "local_only": True})
    assert put.status_code == 200
    d = (await client.post("/api/models/route", headers=h, json={"needs": ["chat"]})).json()["data"]
    assert d["chain"] == ["local:qwen"]                                                     # confidentialité respectée
    r = await client.post("/api/models/route", headers=h, json={"needs": ["vision"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_MODEL_AVAILABLE"
    assert (await client.put("/api/ai-settings", headers=h, json={"mode": "single"})).status_code == 422
    assert (await client.put("/api/ai-settings", headers=h, json={"mode": "bogus"})).status_code == 422
    assert (await client.put("/api/ai-settings", headers=h, json={"weights": {"x": 1}})).status_code == 422
    got = (await client.get("/api/ai-settings", headers=h)).json()["data"]
    assert got["local_only"] is True and got["mode"] == "auto"


async def test_monthly_budget_blocks_or_requires_confirmation(client):
    h = await signup(client, "a@x.io")
    _, project = await make_project(client, h)
    from app.core import db
    from app.models.entities import UsageRecord
    async with db.session_maker()() as s:
        s.add(UsageRecord(organization_id=uuid.UUID(h["X-Organization-Id"]), agent="coder", model="cloud:big",
                          tokens=10, cost_usd=2.0))
        await s.commit()
    body = {"project_id": project, "mission": "x"}
    assert (await client.post("/api/executions", headers=h, json=body)).status_code == 202   # pas de budget défini
    await client.put("/api/ai-settings", headers=h, json={"monthly_budget_usd": 1.0, "on_limit": "block"})
    r = await client.post("/api/executions", headers=h, json=body)
    assert r.status_code == 402 and r.json()["error"]["code"] == "BUDGET_EXCEEDED"
    await client.put("/api/ai-settings", headers=h, json={"monthly_budget_usd": 1.0, "on_limit": "confirm"})
    r = await client.post("/api/executions", headers=h, json=body)
    assert r.status_code == 402 and r.json()["error"]["code"] == "BUDGET_CONFIRMATION_REQUIRED"
    assert (await client.post("/api/executions?confirm_budget=true", headers=h, json=body)).status_code == 202
