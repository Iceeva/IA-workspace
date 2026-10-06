import asyncio
import struct
import tempfile
from pathlib import Path

from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.runtimes import gguf, hardware, quantization
from app.runtimes.benchmark import BASIC_SUITE, run_benchmark
from app.runtimes.registry import KIND_CAPS, RuntimeInfo, RuntimeRegistry, detect_local


def _s(x: str) -> bytes:
    b = x.encode(); return struct.pack("<Q", len(b)) + b


def make_gguf(path: Path, *, file_type=15, extra_pad=1000, version=3):
    kv = [("general.architecture", 8, _s("qwen3")), ("general.name", 8, _s("Qwen3-8B-Instruct")),
          ("general.file_type", 4, struct.pack("<I", file_type)),
          ("qwen3.context_length", 4, struct.pack("<I", 40960)), ("qwen3.block_count", 4, struct.pack("<I", 36)),
          ("qwen3.embedding_length", 4, struct.pack("<I", 4096)),
          ("qwen3.attention.head_count", 4, struct.pack("<I", 32)),
          ("qwen3.attention.head_count_kv", 4, struct.pack("<I", 8)),
          ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 3) + _s("a") + _s("bb") + _s("ccc")),
          ("tokenizer.ggml.scores", 9, struct.pack("<IQ", 6, 3) + struct.pack("<3f", 0, 1, 2))]
    body = b"".join(_s(k) + struct.pack("<I", t) + v for k, t, v in kv)
    path.write_bytes(b"GGUF" + struct.pack("<I", version) + struct.pack("<QQ", 291, len(kv)) + body + b"\0" * extra_pad)


def test_gguf_inspection_reads_metadata_and_skips_arrays():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Qwen3-8B-Q4_K_M.gguf"; make_gguf(p)
        i = gguf.inspect(p)
        assert (i.architecture, i.quantization, i.context_length, i.tensor_count) == ("qwen3", "Q4_K_M", 40960, 291)
        assert i.capabilities == ["chat"] and "ollama" in i.runtimes
        # K/V : 2 · 36 couches · 4096 ctx · 8 têtes kv · 128 dim · 2 octets
        assert i.kv_cache_bytes(4096) == 2 * 36 * 4096 * 8 * 128 * 2
        assert i.memory_needed_gb(4096) > i.size_gb
        assert i.to_dict()["file_name"] == "Qwen3-8B-Q4_K_M.gguf"


def test_gguf_quant_falls_back_to_filename_and_rejects_bad_files():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "model-Q6_K.gguf"; make_gguf(p, file_type=9999)
        assert gguf.inspect(p).quantization == "Q6_K"
        bad = Path(d) / "x.gguf"; bad.write_bytes(b"NOPE" + b"\0" * 40)
        for f, msg in ((bad, "signature"), (Path(d) / "x.txt", "Extension")):
            try:
                gguf.inspect(f); assert False
            except gguf.GGUFError as e:
                assert msg in str(e)
        t = Path(d) / "t.gguf"; t.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 1, 5))
        try:
            gguf.inspect(t); assert False
        except gguf.GGUFError as e:
            assert "tronqué" in str(e)
        v1 = Path(d) / "v1.gguf"; make_gguf(v1, version=1)
        try:
            gguf.inspect(v1); assert False
        except gguf.GGUFError as e:
            assert "Version" in str(e)


def test_gguf_capabilities_inference():
    assert gguf.infer_capabilities("Qwen2.5-Coder-7B-Instruct", "qwen2") == ["chat", "code"]
    assert gguf.infer_capabilities("llava-v1.6-instruct", "llama") == ["chat", "vision"]
    assert gguf.infer_capabilities("nomic-embed", "nomic-bert") == ["embedding"]
    assert gguf.infer_capabilities("Llama-3-8B", "llama") == ["base-model"]


def test_nvidia_smi_parsing_and_fit():
    gpus = hardware.parse_nvidia_smi("NVIDIA GeForce RTX 4060, Laptop GPU, 8188\nNVIDIA A100, 40960\nbroken line\n")
    assert [(g.name, g.vram_mb) for g in gpus] == [("NVIDIA GeForce RTX 4060, Laptop GPU", 8188), ("NVIDIA A100", 40960)]
    hp = hardware.HardwareProfile("Linux", "6", "x86_64", "cpu", 8, 16384, 12000, 100.0, gpus[:1])
    assert hardware.fit(hp, 6.0) == "gpu_full" and hardware.fit(hp, 14.0) == "gpu_partial"
    cpu = hardware.HardwareProfile("Linux", "6", "x86_64", "cpu", 8, 16384, 12000, 100.0)
    assert hardware.fit(cpu, 8.0) == "cpu" and hardware.fit(cpu, 40.0) == "too_large"
    rec = hardware.recommend(hp, [{"name": "70b", "memory_needed_gb": 45}, {"name": "8b", "memory_needed_gb": 6}])
    assert [r["name"] for r in rec] == ["8b", "70b"] and rec[1]["fit"] == "too_large"


def test_detect_runs_on_this_machine_without_crashing():
    p = hardware.detect(run=lambda c: None)
    assert p.os and p.threads >= 1 and p.ram_total_mb > 0 and p.disk_free_gb > 0 and p.to_dict()["vram_mb"] == 0


def test_quantization_trade_offs_are_monotonic():
    rows = quantization.compare(8, 4096, ["FP16", "Q8_0", "Q4_K_M", "Q2_K"])
    sizes = [r.size_gb for r in rows]; speeds = [r.speed_x for r in rows]; q = [r.quality for r in rows]
    assert sizes == sorted(sizes, reverse=True) and speeds == sorted(speeds) and q == sorted(q, reverse=True)
    assert rows[0].size_gb == 16.0 and rows[0].kind == "lossy"
    best = quantization.best_fit(quantization.compare(8, 4096, vram_gb=8, ram_gb=32))
    assert best.fmt in ("Q6_K", "Q5_K_M", "Q4_K_M") and best.fits_gpu
    assert quantization.compare(70, 4096, ["Q4_K_M"], ram_gb=16)[0].fits_ram is False
    for bad in (lambda: quantization.compare(0), lambda: quantization.compare(8, formats=["Q9"])):
        try:
            bad(); assert False
        except ValueError:
            pass


def test_runtime_registry_routes_capabilities_to_connected_runtimes_only():
    reg = RuntimeRegistry()
    reg.register(RuntimeInfo("sana", "sana", "Sana", "http://127.0.0.1:9000", status="connected"))
    reg.register(RuntimeInfo("phonon", "phonon", "Phonon", "http://127.0.0.1:9001", status="unreachable"))
    assert [r.id for r in reg.find("text-to-image")] == ["sana"]
    assert reg.find("speech-to-text") == [] and [r.id for r in reg.find("speech-to-text", connected_only=False)] == ["phonon"]
    assert KIND_CAPS["ollama"] >= {"chat"}


def test_detect_local_runtimes_with_fake_fetch():
    async def fetch(url, timeout):
        if url.endswith("11434/api/tags"):
            return 200, {"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]}
        if url.endswith("1234/v1/models"):
            return 200, {"data": [{"id": "gguf-model"}]}
        return 0, None
    reg = RuntimeRegistry()
    found = asyncio.run(detect_local(reg, fetch))
    assert sorted(r.id for r in found) == ["lmstudio", "ollama"]
    assert reg.get("ollama").models == ["qwen3:8b", "llama3.2:3b"] and reg.get("vllm").status == "unreachable"
    async def down(url, timeout): return 0, None
    asyncio.run(detect_local(reg, down))
    assert reg.get("ollama").status == "unreachable" and reg.get("ollama").models == ["qwen3:8b", "llama3.2:3b"]


class Fake(LLMProvider):
    name = "fake"
    def __init__(self, fail_every=None): self.n, self.fail_every = 0, fail_every
    async def chat(self, *a, **k): raise NotImplementedError
    async def stream(self, messages, *, model, **k):
        self.n += 1
        if self.fail_every and self.n % self.fail_every == 0: raise LLMError("boom")
        await asyncio.sleep(0.05 if self.n == 1 else 0.01)  # 1er appel plus lent : « démarrage à froid »
        q = messages[0].content
        ans = {"17": "391", "capitale": "Paris", "JSON": '{"ok": true}', "fonction": "def add(a,b): return a+b",
               "Traduis": "hello"}
        text = next((v for k, v in ans.items() if k in q), "texte de réponse")
        for w in text.split(" "): yield w + " "
        yield LLMResponse(text, model, 5, 20)


def test_benchmark_measures_latency_throughput_quality_and_resources():
    peaks = iter(range(100, 10000, 100))
    rep = asyncio.run(run_benchmark(Fake(), "m", runs=3, quality=BASIC_SUITE, sampler=lambda: {"ram_used_mb": next(peaks)},
                                    sample_every_s=0.01))
    assert rep.success_rate == 1.0 and rep.ttft_ms_median is not None and rep.tokens_per_s > 0
    assert rep.cold_start_ms is not None and rep.cold_start_ms > 20      # le 1er essai est plus lent
    assert rep.quality_pass_rate == 1.0 and rep.latency_stdev_ms is not None and rep.peak["ram_used_mb"] >= 100


def test_benchmark_reports_instability():
    rep = asyncio.run(run_benchmark(Fake(fail_every=2), "m", runs=4))
    assert rep.success_rate == 0.5 and len(rep.errors) == 2 and "boom" in rep.errors[0]
    dead = asyncio.run(run_benchmark(Fake(fail_every=1), "m", runs=2))
    assert dead.success_rate == 0 and dead.tokens_per_s is None
