"""Hardware Profiler (§32, §42) : CPU, RAM, GPU, VRAM, disque. Multiplateforme, dépendances facultatives."""
from __future__ import annotations
import ctypes
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Callable

Runner = Callable[[list[str]], str | None]


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class GPU:
    name: str
    vram_mb: int
    vendor: str = "unknown"
    unified_memory: bool = False


@dataclass
class HardwareProfile:
    os: str
    os_version: str
    arch: str
    cpu: str
    threads: int
    ram_total_mb: int
    ram_available_mb: int | None
    disk_free_gb: float
    gpus: list[GPU] = field(default_factory=list)
    acceleration: list[str] = field(default_factory=list)

    @property
    def vram_mb(self) -> int:
        return max((g.vram_mb for g in self.gpus), default=0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["vram_mb"] = self.vram_mb
        return d


def parse_nvidia_smi(text: str) -> list[GPU]:
    """Sortie de `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    out = []
    for line in text.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            out.append(GPU(name.strip(), int(float(mem.strip())), "nvidia"))
        except ValueError:
            continue
    return out


def _ram() -> tuple[int, int | None]:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.total // 2**20, vm.available // 2**20
    except ImportError:
        pass
    system = platform.system()
    if system == "Linux":
        try:
            info = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if ":" in l}
            return info["MemTotal"] // 1024, info.get("MemAvailable", 0) // 1024
        except (OSError, KeyError, ValueError):
            pass
    if system == "Windows":
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong),
                        ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        ms = MS(); ms.l = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):  # type: ignore[attr-defined]
            return ms.tp // 2**20, ms.ap // 2**20
    if system == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out and out.strip().isdigit():
            return int(out) // 2**20, None
    return 0, None


def _cpu_name(run: Runner) -> str:
    system = platform.system()
    if system == "Linux":
        try:
            for l in open("/proc/cpuinfo"):
                if l.startswith("model name"):
                    return l.split(":", 1)[1].strip()
        except OSError:
            pass
    if system == "Darwin":
        out = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out:
            return out.strip()
    return platform.processor() or platform.machine()


def detect(path: str = ".", run: Runner = _run) -> HardwareProfile:
    total, avail = _ram()
    p = HardwareProfile(os=platform.system(), os_version=platform.release(), arch=platform.machine(),
                        cpu=_cpu_name(run), threads=os.cpu_count() or 1, ram_total_mb=total,
                        ram_available_mb=avail, disk_free_gb=round(shutil.disk_usage(path).free / 1e9, 1))
    smi = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if smi:
        p.gpus = parse_nvidia_smi(smi)
        if p.gpus:
            p.acceleration.append("cuda")
    if p.os == "Darwin" and p.arch in ("arm64", "aarch64"):
        # Mémoire unifiée : environ 2/3 de la RAM est utilisable par le GPU (estimation).
        p.gpus.append(GPU("Apple Silicon (mémoire unifiée)", int(total * 0.66), "apple", True))
        p.acceleration.append("metal")
    return p


def fit(profile: HardwareProfile, needed_gb: float) -> str:
    """gpu_full | gpu_partial | cpu | too_large — pour un modèle nécessitant `needed_gb`."""
    need = needed_gb * 1024
    avail = profile.ram_available_mb if profile.ram_available_mb is not None else profile.ram_total_mb
    if profile.vram_mb >= need:
        return "gpu_full"
    if profile.vram_mb > 0 and profile.vram_mb + avail * 0.8 >= need:
        return "gpu_partial"
    if avail * 0.8 >= need:
        return "cpu"
    return "too_large"


def recommend(profile: HardwareProfile, candidates: list[dict]) -> list[dict]:
    """candidates : [{name, memory_needed_gb}] → même liste annotée et triée (meilleur ajustement d'abord)."""
    order = {"gpu_full": 0, "gpu_partial": 1, "cpu": 2, "too_large": 3}
    out = [{**c, "fit": fit(profile, c["memory_needed_gb"])} for c in candidates]
    return sorted(out, key=lambda c: (order[c["fit"]], -c["memory_needed_gb"]))


def profile_from_dict(d: dict) -> HardwareProfile:
    """Reconstruit un profil envoyé par le navigateur (relevé par le bridge). Valeurs bornées : c'est une donnée client."""
    def num(k, hi, default=0):
        try:
            return max(0, min(int(d.get(k, default) or default), hi))
        except (TypeError, ValueError):
            return default
    gpus = []
    for g in (d.get("gpus") or [])[:8]:
        if isinstance(g, dict):
            gpus.append(GPU(str(g.get("name", "GPU"))[:80], num_of(g, "vram_mb"), str(g.get("vendor", "unknown"))[:20],
                            bool(g.get("unified_memory", False))))
    avail = d.get("ram_available_mb")
    return HardwareProfile(
        os=str(d.get("os", ""))[:20], os_version=str(d.get("os_version", ""))[:40], arch=str(d.get("arch", ""))[:20],
        cpu=str(d.get("cpu", ""))[:80], threads=num("threads", 4096), ram_total_mb=num("ram_total_mb", 16_000_000),
        ram_available_mb=None if avail is None else num("ram_available_mb", 16_000_000),
        disk_free_gb=float(min(max(float(d.get("disk_free_gb", 0) or 0), 0), 1e7)), gpus=gpus,
        acceleration=[str(a)[:20] for a in (d.get("acceleration") or [])[:8]])


def num_of(g: dict, k: str) -> int:
    try:
        return max(0, min(int(g.get(k, 0) or 0), 4_000_000))
    except (TypeError, ValueError):
        return 0


SIZES_B = (1, 3, 7, 8, 14, 32, 70)


def recommend_models(profile: HardwareProfile, ctx_len: int = 4096, formats=("Q4_K_M", "Q8_0")) -> list[dict]:
    """Quelles tailles de modèle (paramètres × quantification) tiennent sur cette machine, du meilleur ajustement au pire."""
    from . import quantization as Q
    cands = []
    for b in SIZES_B:
        for r in Q.compare(float(b), ctx_len, list(formats)):
            cands.append({"name": f"{b}B {r.fmt}", "params_b": b, "format": r.fmt, "memory_needed_gb": r.memory_gb,
                          "quality": r.quality})
    return recommend(profile, cands)
