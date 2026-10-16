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


# ---- GPU AMD / Intel ------------------------------------------------------------------------------------------------------
import json as _json
import tempfile as _tf
from pathlib import Path as _P

from app.runtimes import hardware as _H


def test_rocm_smi_json_parsing_tolerates_key_variants():
    t = _json.dumps({"card0": {"Card Series": "Radeon RX 7900 XTX", "VRAM Total Memory (B)": "25753026560"},
                     "card1": {"Card SKU": "Radeon PRO W7800", "VRAM Total Memory (B)": str(32 * 2**30)}, "system": {"Driver": "6.x"}})
    g = _H.parse_rocm_smi_json(t)
    assert [(x.name, x.vram_mb, x.vendor) for x in g] == [("Radeon RX 7900 XTX", 24560, "amd"), ("Radeon PRO W7800", 32768, "amd")]
    assert _H.parse_rocm_smi_json("pas du json") == [] and _H.parse_rocm_smi_json("[1]") == []


def test_drm_sysfs_reads_amd_dgpu_and_intel_igpu_and_skips_nvidia():
    with _tf.TemporaryDirectory() as d:
        def card(n, vendor, **files):
            dev = _P(d) / f"card{n}" / "device"
            dev.mkdir(parents=True)
            (dev / "vendor").write_text(vendor + "\n")
            for k, v in files.items():
                (dev / k).write_text(str(v))
        card(0, "0x1002", product_name="AMD Radeon RX 6800", mem_info_vram_total=16 * 2**30, mem_info_gtt_total=8 * 2**30)
        card(1, "0x8086", device="0x46a6")
        card(2, "0x10de", product_name="NVIDIA X")
        (_P(d) / "card0-DP-1").mkdir()                                  # sorties vidéo : ignorées
        g = _H.read_drm_sysfs(d)
    assert [(x.vendor, x.vram_mb, x.unified_memory) for x in g] == [("amd", 16384, False), ("intel", 0, True)]
    assert _H.read_drm_sysfs("/nonexistent") == []


def test_windows_gpu_parsing_prefers_64bit_vram_and_ignores_virtual_adapters():
    a = _json.dumps([{"name": "AMD Radeon RX 7800 XT", "adapter_ram": 4293918720}, {"name": "Intel(R) UHD Graphics 770", "adapter_ram": 1073741824},
                     {"name": "Microsoft Basic Display Adapter", "adapter_ram": 0}, {"name": "NVIDIA GeForce RTX 4070", "adapter_ram": 4293918720}])
    b = _json.dumps({"name": "AMD Radeon RX 7800 XT", "vram": 16 * 2**30})          # un seul objet : ConvertTo-Json ne met pas de liste
    g = _H.parse_windows_gpus(a, b)
    assert [(x.name, x.vram_mb, x.vendor, x.unified_memory) for x in g] == [
        ("AMD Radeon RX 7800 XT", 16384, "amd", False), ("Intel(R) UHD Graphics 770", 1024, "intel", True)]
    assert _H.parse_windows_gpus("", "") == [] and _H.parse_windows_gpus("{oups", "") == []


def test_detect_gpus_linux_amd_with_rocm_and_intel_igpu_shares_system_memory():
    with _tf.TemporaryDirectory() as d:
        dev = _P(d) / "card0" / "device"; dev.mkdir(parents=True)
        (dev / "vendor").write_text("0x8086")
        def run(cmd):
            return None                                                       # ni rocm-smi ni sycl-ls
        g, accel = _H.detect_gpus("Linux", 16000, run, d)
        assert g[0].vendor == "intel" and g[0].vram_mb == 8000 and accel == ["vulkan"]
        rocm = _json.dumps({"card0": {"Card Series": "Radeon RX 7900", "VRAM Total Memory (B)": str(24 * 2**30)}})
        g, accel = _H.detect_gpus("Linux", 16000, lambda c: rocm if c[0] == "rocm-smi" else None, d)
        assert g[0].vram_mb == 24576 and accel == ["rocm", "vulkan"]
        g, accel = _H.detect_gpus("Linux", 16000, lambda c: "x" if c[0] == "sycl-ls" else None, d)
        assert accel == ["sycl", "vulkan"]
    assert _H.detect_gpus("Darwin", 16000, lambda c: None) == ([], [])


def test_amd_gpu_changes_model_fit():
    p = _H.HardwareProfile("Linux", "6", "x86_64", "cpu", 8, 16000, 12000, 100.0, [_H.GPU("Radeon RX 7900", 24576, "amd")], ["vulkan"])
    assert _H.fit(p, 10) == "gpu_full" and _H.fit(p, 30) == "gpu_partial"


def test_runtime_to_dict_never_exposes_api_key():
    from app.runtimes.registry import RuntimeInfo
    r = RuntimeInfo("sana", "sana", "Sana", "http://127.0.0.1:8020", requirements={"api_key": "sk-secret", "paths": {"image": "/x"}})
    d = r.to_dict()
    assert "sk-secret" not in repr(d) and d["requirements"] == {"paths": {"image": "/x"}}
    assert r.requirements["api_key"] == "sk-secret"            # la copie interne reste utilisable par le bridge


def test_benchmark_reports_baseline_and_delta_and_survives_a_broken_sampler():
    from app.runtimes.benchmark import summarize_samples, is_local_endpoint
    vals = iter([1000, 1000, 3000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000])
    rep = asyncio.run(run_benchmark(Fake(), "m", runs=2, sampler=lambda: {"ram_used_mb": next(vals, 5000), "x": "texte"}, sample_every_s=0.005))
    assert rep.baseline == {"ram_used_mb": 1000}                       # mesuré avant le 1er appel
    assert rep.peak["ram_used_mb"] >= 3000 and rep.delta["ram_used_mb"] == rep.peak["ram_used_mb"] - 1000
    assert "x" not in rep.peak                                         # valeurs non numériques ignorées
    def boom(): raise RuntimeError("nvidia-smi absent")
    rep = asyncio.run(run_benchmark(Fake(), "m", runs=1, sampler=boom, sample_every_s=0.01))
    assert rep.success_rate == 1.0 and rep.peak == {} and rep.delta == {}
    s = summarize_samples([{"ram_used_mb": 10, "cpu_percent": 1}, {"ram_used_mb": 30}, "n'importe quoi", {}])
    assert s["baseline"]["ram_used_mb"] == 10 and s["peak"]["ram_used_mb"] == 30 and s["delta"] == {"ram_used_mb": 20, "cpu_percent": 0}
    assert summarize_samples([]) == {"baseline": {}, "peak": {}, "delta": {}}
    assert is_local_endpoint("http://127.0.0.1:11434/v1") and is_local_endpoint("http://localhost:8080")
    assert not is_local_endpoint("https://api.openai.com/v1") and not is_local_endpoint(None) and not is_local_endpoint("http://192.168.1.5:8080")
