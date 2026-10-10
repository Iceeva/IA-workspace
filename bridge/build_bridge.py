"""Construit le Local Bridge en exécutable autonome (PyInstaller) : `aiw-bridge-<triplet>[.exe]`.

Le nom à triplet est celui qu'attend Tauri pour un binaire externe (`bundle.externalBin: ["binaries/aiw-bridge"]`) : le
programme d'installation de l'application embarque alors le bridge, sans Python chez l'utilisateur.

    pip install pyinstaller && python bridge/build_bridge.py            # → frontend/src-tauri/binaries/
    python bridge/build_bridge.py --out dist-bridge                       # ailleurs
PyInstaller ne compile pas en croisé : lancez-le sur chaque OS visé (voir .github/workflows/release.yml)."""
from __future__ import annotations
import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPLES = {
    ("Windows", "amd64"): "x86_64-pc-windows-msvc", ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "arm64"): "aarch64-pc-windows-msvc",
    ("Darwin", "arm64"): "aarch64-apple-darwin", ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu", ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
}


def target_triple(system: str | None = None, machine: str | None = None, rustc_output: str | None = None) -> str:
    """Triplet Rust de la machine : lu dans `rustc -vV` s'il est disponible (source de vérité de Tauri), sinon déduit."""
    if rustc_output:
        m = re.search(r"^host:\s*(\S+)", rustc_output, re.M)
        if m:
            return m.group(1)
    key = (system or platform.system(), (machine or platform.machine()).lower())
    if key not in TRIPLES:
        raise SystemExit(f"Plateforme non prise en charge : {key}")
    return TRIPLES[key]


def _rustc() -> str | None:
    try:
        return subprocess.run(["rustc", "-vV"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "frontend" / "src-tauri" / "binaries"))
    ap.add_argument("--triple", help="remplace le triplet détecté")
    a = ap.parse_args()
    triple = a.triple or target_triple(rustc_output=_rustc())
    exe = ".exe" if "windows" in triple else ""
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "bridge"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", f"aiw-bridge-{triple}",
           "--paths", str(ROOT / "backend"), "--paths", str(ROOT / "bridge"),
           "--distpath", str(out), "--workpath", str(work), "--specpath", str(work), str(ROOT / "bridge" / "entry.py")]
    subprocess.run(cmd, check=True)
    built = out / f"aiw-bridge-{triple}{exe}"
    if not built.exists():
        raise SystemExit(f"Binaire attendu introuvable : {built}")
    shutil.rmtree(work, ignore_errors=True)
    print(f"OK : {built} ({built.stat().st_size // 1024 // 1024} Mo)")


if __name__ == "__main__":
    main()
