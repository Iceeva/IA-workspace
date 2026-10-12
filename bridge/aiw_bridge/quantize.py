"""Quantification réelle d'un fichier GGUF local (§30) avec `llama-quantize` (llama.cpp), pilotée par le bridge.

Pour rester sûr : le fichier source doit être dans un dossier de modèles autorisé ; le type de sortie est dans une liste
blanche ; le binaire est lancé sans shell (arguments en liste) ; le fichier de sortie ne remplace jamais un fichier existant ;
l'espace disque est vérifié ; le travail tourne en arrière-plan (état consultable), annulable.
Requantifier un modèle déjà quantifié dégrade la qualité : refusé sauf demande explicite (`allow_requantize`)."""
from __future__ import annotations
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# types acceptés par llama-quantize (noms officiels) ; BF16/F16/F32 sont des conversions de précision, pas de la quantification
TYPES = {"Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L", "Q4_0", "Q4_1", "Q4_K_S", "Q4_K_M", "Q5_0", "Q5_1", "Q5_K_S", "Q5_K_M", "Q6_K", "Q8_0"}
FULL_PRECISION = {"F32", "F16", "BF16"}
TIMEOUT_S = 4 * 3600


class QuantizeError(ValueError):
    pass


def find_binary(env: dict | None = None) -> str | None:
    """`AIW_LLAMA_QUANTIZE` (chemin explicite) sinon `llama-quantize` dans le PATH."""
    e = env if env is not None else os.environ
    p = e.get("AIW_LLAMA_QUANTIZE")
    if p:
        return p if Path(p).is_file() else None
    return shutil.which("llama-quantize")


def plan(src: Path, target: str, source_quant: str, *, allow_requantize: bool = False, free_bytes: int | None = None) -> Path:
    """Valide la demande et renvoie le chemin de sortie ; QuantizeError sinon."""
    target = target.upper()
    if target not in TYPES:
        raise QuantizeError(f"Type de quantification non pris en charge : {target[:20]}")
    if src.suffix.lower() != ".gguf":
        raise QuantizeError("Extension .gguf attendue")
    if source_quant.upper() not in FULL_PRECISION and not allow_requantize:
        raise QuantizeError(f"Ce fichier est déjà quantifié ({source_quant}) : requantifier dégrade la qualité. "
                            "Partez du modèle F16/BF16, ou confirmez avec allow_requantize.")
    if source_quant.upper() == target:
        raise QuantizeError("Le fichier est déjà dans ce format")
    out = src.with_name(f"{src.stem}-{target}.gguf")
    if out.exists():
        raise QuantizeError(f"{out.name} existe déjà : supprimez-le ou choisissez un autre type")
    need = int(src.stat().st_size * 0.6)                       # la sortie fait au plus ~60 % de la source (Q8_0 ≈ 53 % de F16)
    free = free_bytes if free_bytes is not None else shutil.disk_usage(src.parent).free
    if free < need:
        raise QuantizeError(f"Espace disque insuffisant : {need // 2**30 + 1} Go requis, {free // 2**30} Go libres")
    return out


@dataclass
class Job:
    id: str
    src: str
    out: str
    target: str
    status: str = "running"            # running | done | failed | cancelled
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    _proc: subprocess.Popen | None = None

    def to_dict(self) -> dict:
        end = self.finished or time.time()
        return {"id": self.id, "file": Path(self.out).name, "target": self.target, "status": self.status, "error": self.error,
                "elapsed_s": int(end - self.started),
                "output_mb": (Path(self.out).stat().st_size // 2**20) if self.status == "done" and Path(self.out).exists() else None}


class Quantizer:
    def __init__(self, binary: str | None = None, timeout_s: int = TIMEOUT_S):
        self.binary, self.timeout_s = binary, timeout_s
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, src: Path, target: str, source_quant: str, *, allow_requantize: bool = False, threads: int | None = None) -> Job:
        bin_ = self.binary or find_binary()
        if not bin_:
            raise QuantizeError("llama-quantize est introuvable : installez llama.cpp ou définissez AIW_LLAMA_QUANTIZE")
        with self._lock:
            if any(j.status == "running" for j in self.jobs.values()):
                raise QuantizeError("Une quantification est déjà en cours")
            out = plan(src, target, source_quant, allow_requantize=allow_requantize)
            job = Job(uuid.uuid4().hex[:12], str(src), str(out), target.upper())
            self.jobs[job.id] = job
        cmd = [bin_] + (["--allow-requantize"] if source_quant.upper() not in FULL_PRECISION else []) + [str(src), str(out), job.target]
        if threads and 1 <= threads <= 256:
            cmd.append(str(threads))
        threading.Thread(target=self._run, args=(job, cmd), daemon=True).start()
        return job

    def _run(self, job: Job, cmd: list[str]) -> None:
        tmp = Path(job.out).with_suffix(".gguf.part")             # écrit à part : un échec ne laisse jamais un faux fichier valide
        cmd = [c if c != job.out else str(tmp) for c in cmd]
        try:
            job._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                _, err = job._proc.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                job._proc.kill(); job._proc.communicate()
                raise QuantizeError("Délai dépassé")
            if job.status == "cancelled":
                tmp.unlink(missing_ok=True); return
            if job._proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
                raise QuantizeError((err or "llama-quantize a échoué").strip().splitlines()[-1][:200] if (err or "").strip() else "llama-quantize a échoué")
            os.replace(tmp, job.out)
            job.status = "done"
        except (QuantizeError, OSError) as e:
            tmp.unlink(missing_ok=True)
            if job.status != "cancelled":
                job.status, job.error = "failed", str(e)
        finally:
            job.finished = time.time()

    def cancel(self, job_id: str) -> bool:
        j = self.jobs.get(job_id)
        if not j or j.status != "running":
            return False
        j.status = "cancelled"
        if j._proc:
            j._proc.kill()
        return True
