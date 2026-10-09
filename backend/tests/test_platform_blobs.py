import asyncio
import os
import tempfile
import uuid

from app.services import blobs


def run(c): return asyncio.run(c)


def setup(d):
    from app.core.crypto import SecretBox
    os.environ.update(STORAGE_PROVIDER="local", STORAGE_LOCAL_DIR=d)
    blobs.get_secretbox = lambda: SecretBox(["une-cle-de-test-suffisamment-longue-123"])


def test_store_load_roundtrip_and_dedup_and_org_isolation():
    with tempfile.TemporaryDirectory() as d:
        setup(d)
        a, b = uuid.uuid4(), uuid.uuid4()
        data = b"bonjour " * 5000
        k1 = run(blobs.store(a, data)); k2 = run(blobs.store(a, data)); k3 = run(blobs.store(b, data))
        assert k1 == k2 and k1.startswith("cas:") and k3 != k1                # dédup dans l'org, pas entre orgs
        files = [f for _, _, fs in os.walk(d) for f in fs]
        assert len(files) == 2                                               # 1 objet par org, pas 3
        raw = open(next(os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs), "rb").read()
        assert b"bonjour" not in raw and len(raw) < len(data) // 10          # chiffré ET compressé
        assert run(blobs.load(a, k1)) == data


def test_load_legacy_key_and_deletable_rule():
    with tempfile.TemporaryDirectory() as d:
        setup(d)
        from app.storage.backends import LocalStorage
        run(LocalStorage(d).put("org/legacy1", b"ancien", "text/plain"))
        assert run(blobs.load(uuid.uuid4(), "org/legacy1")) == b"ancien"
    assert blobs.deletable("org/legacy1", 5) and blobs.deletable("cas:ab", 0) and not blobs.deletable("cas:ab", 1)
