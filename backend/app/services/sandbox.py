"""Exécution de code utilisateur : toujours dans un conteneur jetable, jamais dans l'API ni le worker.
CPU/RAM/PID limités, aucun réseau, système de fichiers en lecture seule, délai strict."""
import asyncio, shutil, tempfile
from dataclasses import dataclass
from pathlib import Path

IMAGES = {"python": ("python:3.12-slim", ["python", "/work/main.py"], "main.py"),
          "node": ("node:22-slim", ["node", "/work/main.js"], "main.js"),
          "shell": ("python:3.12-slim", ["sh", "/work/main.sh"], "main.sh")}  # terminal ISOLÉ : jamais l'hôte


class SandboxUnavailable(RuntimeError):
    pass


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def build_command(language: str, workdir: str, *, cpus: float = 0.5, memory_mb: int = 256, name: str) -> list[str]:
    if language not in IMAGES:
        raise ValueError(f"Langage non supporté: {language}")
    image, cmd, _ = IMAGES[language]
    return ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
            "--cpus", str(cpus), "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m",
            "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534", "--tmpfs", "/tmp:size=16m,noexec",
            "-v", f"{workdir}:/work:ro", image, *cmd]


async def run_code(language: str, code: str, timeout_s: int = 10, max_output: int = 20_000) -> SandboxResult:
    if shutil.which("docker") is None:
        raise SandboxUnavailable("Docker est requis pour l'exécution isolée de code")
    import uuid
    name = f"aiw-sbx-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory() as d:
        Path(d, IMAGES[language][2]).write_text(code, encoding="utf-8")
        Path(d).chmod(0o755)
        proc = await asyncio.create_subprocess_exec(*build_command(language, d, name=name),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
            timed_out = False
        except asyncio.TimeoutError:
            kill = await asyncio.create_subprocess_exec("docker", "kill", name,
                                                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await kill.wait()
            out, err, timed_out = b"", b"", True
    return SandboxResult(proc.returncode if proc.returncode is not None else -1,
                         out.decode("utf-8", "replace")[:max_output], err.decode("utf-8", "replace")[:max_output], timed_out)
