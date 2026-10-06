import io
from app.core.security import create_action_token, pw_fingerprint
from datetime import timedelta
from .conftest import signup


async def make_project(c, h, name="P"):
    w = (await c.post("/api/workspaces", json={"name": "W"}, headers=h)).json()["data"]["id"]
    r = await c.post("/api/projects", json={"workspace_id": w, "name": name}, headers=h)
    return w, r.json()["data"]["id"]


async def test_register_login_me(client):
    h = await signup(client, "a@x.io")
    me = (await client.get("/api/me", headers=h)).json()["data"]
    assert me["email"] == "a@x.io" and me["organizations"][0]["role"] == "OWNER"
    bad = await client.post("/api/auth/login", json={"email": "a@x.io", "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_tenant_isolation(client):
    a, b = await signup(client, "a@x.io", "A"), await signup(client, "b@x.io", "B")
    w, p = await make_project(client, a)
    assert (await client.get("/api/projects", headers=b)).json()["data"] == []
    # B invoque l'organisation de A : refus 404, pas de fuite
    cross = {"Authorization": b["Authorization"], "X-Organization-Id": a["X-Organization-Id"]}
    assert (await client.get("/api/projects", headers=cross)).status_code == 404
    # B tente de créer un projet dans le workspace de A
    r = await client.post("/api/projects", json={"workspace_id": w, "name": "evil"}, headers=b)
    assert r.status_code == 404
    # B tente de lancer une exécution sur le projet de A
    r = await client.post("/api/executions", json={"project_id": p, "mission": "mission piratée"}, headers=b)
    assert r.status_code == 404


async def test_execution_enqueued_and_cancel(client):
    h = await signup(client, "a@x.io")
    _, p = await make_project(client, h)
    r = await client.post("/api/executions", json={"project_id": p, "mission": "Construire une API"}, headers=h)
    assert r.status_code == 202 and client.queued == [r.json()["data"]["id"]]
    c = await client.post(f"/api/executions/{r.json()['data']['id']}/cancel", headers=h)
    assert c.json()["data"]["status"] == "CANCELLING"


async def test_validation_error_format(client):
    h = await signup(client, "a@x.io")
    r = await client.post("/api/agents", json={"name": "x", "role": "hacker", "system_prompt": "s"}, headers=h)
    assert r.status_code == 422 and r.json()["success"] is False and r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_file_upload_rules(client):
    h = await signup(client, "a@x.io")
    _, p = await make_project(client, h)
    ok = await client.post("/api/files", headers=h, data={"project_id": p, "path": "src/a.py"},
                           files={"file": ("a.py", io.BytesIO(b"def f():\n    return 1\n"))})
    assert ok.status_code == 201 and ok.json()["data"]["indexed"] is True
    fid = ok.json()["data"]["id"]
    assert (await client.get(f"/api/files/{fid}/content", headers=h)).json()["data"]["content"].startswith("def f")
    ed = await client.put(f"/api/files/{fid}/content", json={"content": "def f():\n    return 2\n"}, headers=h)
    assert "+    return 2" in ed.json()["data"]["diff"]
    for path, name, data in [("../../etc/x", "x.py", b"1"), ("a.exe", "a.exe", b"MZ"), ("p.png", "p.png", b"not png")]:
        r = await client.post("/api/files", headers=h, data={"path": path}, files={"file": (name, io.BytesIO(data))})
        assert r.status_code == 422, (path, r.text)
    assert (await client.delete(f"/api/files/{fid}", headers=h)).status_code == 204


async def test_rbac_viewer_cannot_write(client):
    from sqlalchemy import update
    from app.core.db import session_maker
    from app.models.entities import OrganizationMember, Role
    h = await signup(client, "a@x.io")
    async with session_maker()() as s:
        await s.execute(update(OrganizationMember).values(role=Role.VIEWER)); await s.commit()
    r = await client.post("/api/agents", json={"name": "x", "role": "coder", "system_prompt": "s"}, headers=h)
    assert r.status_code == 403


async def test_admin_requires_platform_admin(client):
    h = await signup(client, "a@x.io")
    assert (await client.get("/api/admin/users", headers=h)).status_code == 403


async def test_memory_scope_and_api_key_auth(client):
    h = await signup(client, "a@x.io")
    assert (await client.post("/api/memory", json={"scope": "project", "scope_id": "p1", "content": "Utiliser PostgreSQL"}, headers=h)).status_code == 201
    got = (await client.get("/api/memory", params={"scope": "project", "scope_id": "p1", "q": "PostgreSQL"}, headers=h)).json()["data"]
    assert got and got[0]["content"] == "Utiliser PostgreSQL"
    key = (await client.post("/api/api-keys", json={"name": "ci"}, headers=h)).json()["data"]["key"]
    r = await client.get("/api/projects", headers={"X-API-Key": key, "X-Organization-Id": h["X-Organization-Id"]})
    assert r.status_code == 200


async def test_password_reset_is_single_use(client):
    h = await signup(client, "a@x.io")
    from sqlalchemy import select
    from app.core.db import session_maker
    from app.models.entities import User
    async with session_maker()() as s:
        u = (await s.execute(select(User))).scalar_one()
        tok = create_action_token(str(u.id), "reset_password", timedelta(hours=1), pw_fingerprint(u.password_hash))
    ok = await client.post("/api/auth/reset-password", json={"token": tok, "password": "another-long-pass"})
    assert ok.status_code == 200
    again = await client.post("/api/auth/reset-password", json={"token": tok, "password": "third-long-pass-1"})
    assert again.status_code == 400
    assert (await client.post("/api/auth/login", json={"email": "a@x.io", "password": "another-long-pass"})).status_code == 200
