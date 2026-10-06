"""Outils du Code Agent : diff unifié et extraction des fichiers proposés par le Coder."""
import difflib, re
from app.storage.paths import UnsafePath, safe_path

# Format imposé au Coder :  ```python path=src/app.py \n ...code... \n ```
_BLOCK = re.compile(r"```[\w+-]*[ \t]+path=([^\s`]+)[ \t]*\n(.*?)\n```", re.S)
MAX_FILES = 40
MAX_FILE_CHARS = 200_000


def make_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{path}", f"b/{path}", n=3))


def parse_file_blocks(output: str) -> tuple[dict[str, str], list[str]]:
    """Retourne (fichiers valides, chemins rejetés). Un chemin dangereux n'est jamais écrit."""
    files: dict[str, str] = {}
    rejected: list[str] = []
    for raw_path, body in _BLOCK.findall(output):
        try:
            p = safe_path(raw_path)
        except UnsafePath:
            rejected.append(raw_path); continue
        if len(body) > MAX_FILE_CHARS or len(files) >= MAX_FILES:
            rejected.append(raw_path); continue
        files[p] = body
    return files, rejected
