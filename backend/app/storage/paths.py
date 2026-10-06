"""Normalisation de chemins virtuels : aucune sortie possible de la racine du projet."""
import posixpath
import re

MAX_PATH = 400
_BAD = re.compile(r"[\x00-\x1f\\:*?\"<>|]")


class UnsafePath(ValueError):
    pass


def safe_path(raw: str) -> str:
    """Retourne un chemin relatif normalisé ou lève UnsafePath (../, absolu, NUL, antislash…)."""
    if not raw or len(raw) > MAX_PATH or _BAD.search(raw):
        raise UnsafePath("Chemin invalide")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise UnsafePath("Chemin absolu interdit")
    parts = raw.split("/")
    if any(p in ("..", "") for p in parts) or any(p.startswith("~") for p in parts[:1]):
        raise UnsafePath("Traversée de répertoire interdite")
    norm = posixpath.normpath(raw)
    if norm.startswith("..") or norm == ".":
        raise UnsafePath("Traversée de répertoire interdite")
    return norm
