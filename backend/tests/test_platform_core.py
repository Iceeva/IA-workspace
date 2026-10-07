import asyncio
import tempfile

from app.core.crypto import CryptoError, SecretBox, mask
from app.services.budget import BudgetPolicy, cost_usd, evaluate
from app.storage import cas
from app.storage.backends import LocalStorage

KEY = "a-very-long-secret-key-for-tests-0123456789"


def test_secretbox_roundtrip_and_tamper_detection():
    b = SecretBox([KEY]); t = b.encrypt("sk-live-ABCDEF123456", aad="org-1")
    assert t.startswith("enc:v1:") and "ABCDEF" not in t
    assert b.decrypt(t, aad="org-1") == "sk-live-ABCDEF123456"
    assert b.encrypt("x") != b.encrypt("x")                      # nonce aléatoire
    for bad in (lambda: b.decrypt(t, aad="org-2"), lambda: b.decrypt(t[:-4] + "AAAA", aad="org-1"),
                lambda: SecretBox(["another-completely-different-key"]).decrypt(t, aad="org-1"),
                lambda: b.decrypt("clair")):
        try:
            bad(); assert False
        except CryptoError:
            pass


def test_key_rotation_new_key_encrypts_old_key_still_decrypts():
    old = SecretBox([KEY]).encrypt("secret")
    rotated = SecretBox(["brand-new-rotation-key-0123456789", KEY])
    assert rotated.decrypt(old) == "secret"
    assert SecretBox(["brand-new-rotation-key-0123456789"]).decrypt(rotated.encrypt("n")) == "n"
    for bad in ([], [""], ["short"]):
        try:
            SecretBox(bad); assert False
        except CryptoError:
            pass


def test_mask_never_reveals_more_than_four_chars():
    assert mask("sk-abcdefghijklmnop") == "••••mnop" and mask("short") == "••••" and mask(None) == ""


def run(c): return asyncio.run(c)


def test_cas_dedup_compression_encryption_and_exact_restore():
    with tempfile.TemporaryDirectory() as d:
        be = LocalStorage(d); store = cas.ContentStore(be, SecretBox([KEY]), "org-1")
        data = (b"def f():\n    return 1\n" * 5000)
        a = run(store.put(data)); b = run(store.put(data))
        assert not a.deduplicated and b.deduplicated and a.hash == b.hash and b.stored_size == 0
        assert a.stored_size < len(data) / 10 and a.codec in (cas.ZLIB, cas.ZSTD)
        assert run(store.get(a.hash)) == data
        raw = (__import__("pathlib").Path(d) / store.key_for(a.hash)).read_bytes()
        assert raw[:1] == b"E" and b"def f" not in raw             # chiffré
        assert run(store.put(b"")).size == 0 and run(store.get(run(store.put(b"")).hash)) == b""


def test_cas_incompressible_data_is_stored_raw_and_scopes_do_not_share():
    import os
    with tempfile.TemporaryDirectory() as d:
        be = LocalStorage(d); box = SecretBox([KEY])
        s1, s2 = cas.ContentStore(be, box, "org-1"), cas.ContentStore(be, box, "org-2")
        blob = os.urandom(4096)
        r = run(s1.put(blob)); assert r.codec == cas.RAW
        r2 = run(s2.put(blob))
        assert r.hash != r2.hash and not r2.deduplicated            # pas de fuite d'existence entre organisations


def test_cas_detects_corruption_swaps_and_missing_key():
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        be = LocalStorage(d); box = SecretBox([KEY]); st = cas.ContentStore(be, box, "o")
        a, b = run(st.put(b"alpha" * 100)), run(st.put(b"bravo" * 100))
        pa = Path(d) / st.key_for(a.hash); raw = bytearray(pa.read_bytes()); raw[-1] ^= 1; pa.write_bytes(bytes(raw))
        for fn in (lambda: run(st.get(a.hash)),):
            try:
                fn(); assert False
            except cas.IntegrityError:
                pass
        pa.write_bytes((Path(d) / st.key_for(b.hash)).read_bytes())       # blob d'un autre objet sous le hash de a
        try:
            run(st.get(a.hash)); assert False
        except cas.IntegrityError:
            pass
        try:
            run(cas.ContentStore(be, None, "o").get(b.hash)); assert False
        except cas.IntegrityError as e:
            assert "clé" in str(e)


def test_cas_without_encryption_still_verifies_integrity():
    with tempfile.TemporaryDirectory() as d:
        st = cas.ContentStore(LocalStorage(d), None, "o"); r = run(st.put(b"hello" * 50))
        assert run(st.get(r.hash)) == b"hello" * 50


def test_zlib_bomb_is_rejected():
    import zlib
    bomb = zlib.compress(b"\0" * 5_000_000)
    try:
        cas.decompress(cas.ZLIB, bomb, max_size=1000); assert False
    except cas.IntegrityError:
        pass


def test_budget_modes():
    assert evaluate(BudgetPolicy(), 999).allowed
    p = BudgetPolicy(50.0, "block")
    d = evaluate(p, 10, 5); assert d.allowed and not d.warn and d.remaining == 40
    assert evaluate(p, 41, 2).warn
    blocked = evaluate(p, 49, 5); assert not blocked.allowed and not blocked.needs_confirmation and "50.00" in blocked.reason
    c = BudgetPolicy(50.0, "confirm")
    ask = evaluate(c, 50, 1); assert not ask.allowed and ask.needs_confirmation
    assert evaluate(c, 50, 1, confirmed=True).allowed
    try:
        evaluate(BudgetPolicy(1, "x"), 0); assert False
    except ValueError:
        pass
    assert cost_usd(1_000_000, 500_000, 3.0, 15.0) == 10.5
