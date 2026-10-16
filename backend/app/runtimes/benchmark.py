"""Benchmark de modèles (§31) : latence, débit, stabilité, ressources, contrôle de qualité rapide.

Fonctionne avec n'importe quel LLMProvider (local ou cloud). Les contrôles de qualité sont un test de bon
sens (instructions, arithmétique, format JSON), pas un benchmark académique."""
from __future__ import annotations
import asyncio
import json
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable

from app.llm.base import LLMProvider, LLMResponse, Message

Check = Callable[[str], bool]
BASIC_SUITE: list[tuple[str, Check]] = [
    ("Combien font 17 * 23 ? Réponds uniquement par le nombre.", lambda t: "391" in t),
    ("Quelle est la capitale de la France ? Un seul mot.", lambda t: "paris" in t.lower()),
    ('Réponds uniquement par un JSON valide {"ok": true}.', lambda t: _json_ok(t)),
    ("Écris une fonction Python nommée add qui additionne deux nombres.", lambda t: "def add" in t),
    ("Traduis « bonjour » en anglais, un seul mot.", lambda t: "hello" in t.lower()),
]


def _json_ok(t: str) -> bool:
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return bool(m) and json.loads(m.group(0)).get("ok") is True
    except ValueError:
        return False


@dataclass
class RunResult:
    ok: bool
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    tokens: int = 0
    error: str | None = None


@dataclass
class BenchReport:
    model: str
    runs: int
    success_rate: float
    ttft_ms_median: float | None
    total_ms_median: float | None
    tokens_per_s: float | None
    cold_start_ms: float | None            # 1er essai − médiane des suivants : proxy du temps de chargement
    latency_stdev_ms: float | None         # stabilité
    quality_pass_rate: float | None
    peak: dict = field(default_factory=dict)      # ressources : maximum observé (si un sampler est fourni)
    baseline: dict = field(default_factory=dict)  # ressources au repos, avant le premier appel
    delta: dict = field(default_factory=dict)     # peak − baseline : ce que le modèle consomme réellement
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


async def _one(provider: LLMProvider, model: str, prompt: str, max_tokens: int) -> tuple[RunResult, str]:
    t0 = time.monotonic()
    first, text, final = None, [], None
    try:
        async for chunk in provider.stream([Message("user", prompt)], model=model, temperature=0.0,
                                           max_tokens=max_tokens):
            if isinstance(chunk, LLMResponse):
                final = chunk
            else:
                if first is None:
                    first = time.monotonic()
                text.append(chunk)
    except Exception as e:  # noqa: BLE001 — l'échec fait partie de la mesure de stabilité
        return RunResult(False, error=f"{type(e).__name__}: {str(e)[:120]}"), ""
    end = time.monotonic()
    out = "".join(text)
    tokens = final.completion_tokens if final and final.completion_tokens else max(1, len(out) // 4)
    return RunResult(True, ((first or end) - t0) * 1000, (end - t0) * 1000, tokens), out


async def run_benchmark(provider: LLMProvider, model: str, *, prompt: str = "Explique en 3 phrases ce qu'est un GGUF.",
                        runs: int = 3, max_tokens: int = 128, quality: list[tuple[str, Check]] | None = None,
                        sampler: Callable[[], dict] | None = None, sample_every_s: float = 0.5) -> BenchReport:
    peak: dict = {}
    baseline: dict = {}
    stop = asyncio.Event()

    async def read() -> dict:
        # le sampler lance des sous-processus (nvidia-smi) : hors de la boucle d'événements
        try:
            return {k: v for k, v in ((await asyncio.to_thread(sampler)) or {}).items() if isinstance(v, (int, float))}
        except Exception:  # noqa: BLE001 — une mesure indisponible ne doit pas faire échouer le benchmark
            return {}

    async def sample():
        while not stop.is_set():
            for k, v in (await read()).items():
                peak[k] = max(peak.get(k, v), v)
            try:
                await asyncio.wait_for(stop.wait(), sample_every_s)
            except asyncio.TimeoutError:
                pass
    if sampler:
        baseline = await read()      # amorce aussi psutil.cpu_percent, dont le 1er appel renvoie 0
        task = asyncio.create_task(sample())
    else:
        task = None
    results = [(await _one(provider, model, prompt, max_tokens))[0] for _ in range(max(1, runs))]
    q_rate = None
    if quality:
        passed = 0
        for p, check in quality:
            r, out = await _one(provider, model, p, max_tokens)
            passed += int(r.ok and check(out))
        q_rate = passed / len(quality)
    if task:
        stop.set(); await task
    good = [r for r in results if r.ok]
    med = statistics.median
    cold = (good[0].total_ms - med([r.total_ms for r in good[1:]])) if len(good) >= 2 else None
    gen_ms = sum(max(r.total_ms - r.ttft_ms, 1e-6) for r in good)
    return BenchReport(
        model=model, runs=len(results), success_rate=len(good) / len(results),
        ttft_ms_median=med([r.ttft_ms for r in good]) if good else None,
        total_ms_median=med([r.total_ms for r in good]) if good else None,
        tokens_per_s=round(sum(r.tokens for r in good) / (gen_ms / 1000), 2) if good else None,
        cold_start_ms=round(cold, 1) if cold is not None else None,
        latency_stdev_ms=round(statistics.stdev([r.total_ms for r in good]), 1) if len(good) >= 2 else None,
        quality_pass_rate=q_rate, peak=peak, baseline=baseline,
        delta={k: round(peak[k] - baseline[k], 1) for k in peak if k in baseline},
        errors=[r.error for r in results if r.error])


def system_sampler() -> dict:
    """Échantillon CPU/RAM (psutil si présent) et VRAM NVIDIA (nvidia-smi). Valeurs absentes = non mesurables."""
    out: dict = {}
    try:
        import psutil
        out["cpu_percent"] = psutil.cpu_percent(interval=None)
        out["ram_used_mb"] = (psutil.virtual_memory().total - psutil.virtual_memory().available) // 2**20
    except ImportError:
        pass
    from .hardware import _run
    smi = _run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    if smi:
        try:
            out["vram_used_mb"] = max(int(float(l)) for l in smi.split() if l.replace(".", "").isdigit())
        except ValueError:
            pass
    return out


def summarize_samples(samples: list[dict]) -> dict:
    """Résume des échantillons système pris ailleurs (bridge) : au repos = 1er échantillon, pic = maximum, delta."""
    rows = [{k: v for k, v in s.items() if isinstance(v, (int, float))} for s in samples if isinstance(s, dict)]
    rows = [r for r in rows if r]
    if not rows:
        return {"baseline": {}, "peak": {}, "delta": {}}
    peak: dict = {}
    for r in rows:
        for k, v in r.items():
            peak[k] = max(peak.get(k, v), v)
    base = rows[0]
    return {"baseline": base, "peak": peak, "delta": {k: round(peak[k] - base[k], 1) for k in peak if k in base}}


def is_local_endpoint(base_url: str | None) -> bool:
    """Vrai si le fournisseur tourne sur la machine du serveur d'API (boucle locale) : seul cas où les ressources
    mesurées côté serveur sont celles du modèle."""
    from urllib.parse import urlparse
    try:
        host = (urlparse(base_url or "").hostname or "").lower()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.startswith("127.")
