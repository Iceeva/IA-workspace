import json
import os
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2] / "backend")]
from aiw_bridge.quantize import QuantizeError, Quantizer, find_binary, plan  # noqa: E402
from aiw_bridge.server import Bridge  # noqa: E402

TOKEN = "t" * 40


def gguf_bytes(ftype: int) -> bytes:
    """GGUF minimal valide : architecture « llama » et general.file_type."""
    import struct
    def s(x): b = x.encode(); return struct.pack("<Q", len(b)) + b
    kv = s("general.architecture") + struct.pack("<I", 8) + s("llama") + s("general.file_type") + struct.pack("<I", 4) + struct.pack("<I", ftype)
    return b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 2) + kv + b"\0" * 4096


def fake_quantize(d: Path, *, fail=False, slow=False) -> str:
    """Faux `llama-quantize` (script Python) : écrit la sortie, ou échoue, ou traîne."""
    p = d / "fake-quantize"
    p.write_text(f"#!{sys.executable}\nimport sys, time\nargs=[a for a in sys.argv[1:] if not a.startswith('--')]\n"
                 + ("time.sleep(30)\n" if slow else "") + ("sys.stderr.write('boom: type invalide\\n'); sys.exit(2)\n" if fail else
                 "open(args[1],'wb').write(b'GGUF'+b'x'*100)\n"))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def wait(job, secs=10):
    t = time.time()
    while job.status == "running" and time.time() - t < secs:
        time.sleep(0.05)


def test_plan_rules():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "m-F16.gguf"; src.write_bytes(b"x" * 1000)
        assert plan(src, "q4_k_m", "F16").name == "m-F16-Q4_K_M.gguf"
        for args, kw in ((("Q99", "F16"), {}), (("Q4_K_M", "Q8_0"), {}), (("Q8_0", "F16"), {"free_bytes": 1})):
            try:
                plan(src, *args, **kw); assert False
            except QuantizeError:
                pass
        assert plan(src, "Q4_K_M", "Q8_0", allow_requantize=True)
        (Path(d) / "m-F16-Q4_K_M.gguf").write_bytes(b"x")
        try:
            plan(src, "Q4_K_M", "F16"); assert False
        except QuantizeError as e:
            assert "existe déjà" in str(e)


def test_job_success_failure_cancel_and_never_overwrites():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); src = d / "m.gguf"; src.write_bytes(gguf_bytes(1))
        q = Quantizer(fake_quantize(d))
        j = q.start(src, "Q4_K_M", "F16"); wait(j)
        assert j.status == "done" and (d / "m-Q4_K_M.gguf").read_bytes().startswith(b"GGUF") and not list(d.glob("*.part"))
        assert j.to_dict()["file"] == "m-Q4_K_M.gguf"
        bad = Quantizer(fake_quantize(d, fail=True)); j = bad.start(src, "Q5_K_M", "F16"); wait(j)
        assert j.status == "failed" and "boom" in j.error and not (d / "m-Q5_K_M.gguf").exists() and not list(d.glob("*.part"))
        slow = Quantizer(fake_quantize(d, slow=True)); j = slow.start(src, "Q6_K", "F16")
        try:
            slow.start(src, "Q8_0", "F16"); assert False                       # un seul travail à la fois
        except QuantizeError:
            pass
        assert slow.cancel(j.id); wait(j); assert j.status == "cancelled" and not (d / "m-Q6_K.gguf").exists()
        try:
            Quantizer(None).start(src, "Q8_0", "F16") if find_binary({}) is None else None
        except QuantizeError as e:
            assert "introuvable" in str(e)


def test_find_binary_uses_explicit_env_path():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "lq"; f.write_text("x")
        assert find_binary({"AIW_LLAMA_QUANTIZE": str(f)}) == str(f) and find_binary({"AIW_LLAMA_QUANTIZE": str(f) + "x"}) is None


def test_bridge_quantize_endpoint_guards_paths_and_reports_status():
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
        d, other = Path(d), Path(other)
        (d / "m.gguf").write_bytes(gguf_bytes(1)); (d / "q.gguf").write_bytes(gguf_bytes(15)); (other / "x.gguf").write_bytes(gguf_bytes(1))
        b = Bridge(TOKEN, ["https://app.example"], [str(d)], detect=lambda: None)
        b.quantizer = Quantizer(fake_quantize(d))
        srv = b.serve(port=0); threading.Thread(target=srv.serve_forever, daemon=True).start()
        def call(path, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{b.port}{path}", json.dumps(body).encode() if body is not None else None,
                                         {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "Host": f"127.0.0.1:{b.port}"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            assert call("/quantize", {"path": str(other / "x.gguf"), "type": "Q4_K_M"})[0] == 403          # hors dossiers autorisés
            s, r = call("/quantize", {"path": str(d / "q.gguf"), "type": "Q8_0"}); assert s == 422 and "déjà quantifié" in r["error"]["message"]
            s, r = call("/quantize", {"path": str(d / "m.gguf"), "type": "Q4_K_M"}); assert s == 202 and r["data"]["status"] in ("running", "done")
            time.sleep(1.5)
            s, r = call("/quantize"); assert s == 200 and r["data"]["jobs"][0]["status"] == "done" and "Q4_K_M" in r["data"]["types"] and r["data"]["available"]
        finally:
            srv.shutdown()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
