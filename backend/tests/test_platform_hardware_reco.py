from app.runtimes.hardware import profile_from_dict, recommend_models


def test_profile_from_dict_clamps_and_tolerates_garbage():
    p = profile_from_dict({"os": "Linux", "threads": "abc", "ram_total_mb": 10**12, "gpus": [{"name": "X" * 500, "vram_mb": -5}, "zzz"],
                           "disk_free_gb": "nan?"[:0] or 5, "acceleration": ["cuda"] * 50})
    assert p.threads == 0 and p.ram_total_mb == 16_000_000 and len(p.gpus) == 1 and p.gpus[0].vram_mb == 0
    assert len(p.gpus[0].name) == 80 and len(p.acceleration) == 8


def test_recommend_models_orders_by_fit():
    gpu = profile_from_dict({"ram_total_mb": 32768, "ram_available_mb": 24000, "gpus": [{"name": "RTX", "vram_mb": 12288, "vendor": "nvidia"}]})
    rows = recommend_models(gpu)
    fits = [r["fit"] for r in rows]
    assert fits == sorted(fits, key=["gpu_full", "gpu_partial", "cpu", "too_large"].index)
    assert any(r["name"] == "8B Q4_K_M" and r["fit"] == "gpu_full" for r in rows)
    assert any(r["name"] == "70B Q8_0" and r["fit"] == "too_large" for r in rows)
    tiny = profile_from_dict({"ram_total_mb": 4096, "ram_available_mb": 2048})
    assert next(r for r in recommend_models(tiny) if r["name"] == "8B Q4_K_M")["fit"] == "too_large"
