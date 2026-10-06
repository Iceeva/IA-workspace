"""Lecture des métadonnées d'un fichier .gguf (§11) sans charger les poids : seul l'en-tête est parcouru."""
from __future__ import annotations
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"GGUF"
_SCALARS = {0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4),
            7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8)}
# Valeurs de `general.file_type` (llama_ftype). Les types non listés retombent sur le nom de fichier.
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
              12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
              32: "BF16"}
_QUANT_RE = re.compile(r"(IQ\d_[A-Z]+|Q\d_K_[SML]|Q\d_K|Q\d_\d|BF16|F16|F32|FP16)", re.I)
MAX_KV = 200_000
MAX_STR = 1 << 26
GGUF_RUNTIMES = ("llamacpp", "ollama", "lmstudio", "localai")  # tous savent charger du GGUF


class GGUFError(ValueError):
    pass


@dataclass
class GGUFInfo:
    path: str
    file_name: str
    size_bytes: int
    version: int
    tensor_count: int
    architecture: str
    name: str
    quantization: str
    context_length: int | None
    block_count: int | None
    embedding_length: int | None
    head_count: int | None
    head_count_kv: int | None
    capabilities: list[str] = field(default_factory=list)
    runtimes: tuple[str, ...] = GGUF_RUNTIMES

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1e9

    def kv_cache_bytes(self, ctx: int | None = None) -> int:
        """Cache K/V en fp16 : 2 · couches · contexte · têtes_kv · dim_tête · 2 octets (estimation)."""
        ctx = ctx or self.context_length or 4096
        if not (self.block_count and self.embedding_length and self.head_count):
            return int(ctx * 128 * 1024)  # repli grossier : ≈ 128 Ko/token (modèle 8B)
        head_dim = self.embedding_length // self.head_count
        return 2 * self.block_count * ctx * (self.head_count_kv or self.head_count) * head_dim * 2

    def memory_needed_gb(self, ctx: int | None = None) -> float:
        """Poids + cache K/V + 10 % + 0,5 Go de surcoût d'exécution. Estimation, pas une garantie."""
        return round((self.size_bytes + self.kv_cache_bytes(ctx)) * 1.1 / 1e9 + 0.5, 2)

    def to_dict(self, ctx: int | None = None) -> dict:
        return {"file_name": self.file_name, "size_gb": round(self.size_gb, 2), "gguf_version": self.version,
                "tensor_count": self.tensor_count, "architecture": self.architecture, "name": self.name,
                "quantization": self.quantization, "context_length": self.context_length,
                "capabilities": self.capabilities, "memory_needed_gb": self.memory_needed_gb(ctx),
                "compatible_runtimes": list(self.runtimes)}


def _read(f, fmt: str, size: int):
    b = f.read(size)
    if len(b) != size:
        raise GGUFError("Fichier GGUF tronqué")
    return struct.unpack(fmt, b)[0]


def _string(f) -> str:
    n = _read(f, "<Q", 8)
    if n > MAX_STR:
        raise GGUFError("Chaîne GGUF anormalement longue")
    b = f.read(n)
    if len(b) != n:
        raise GGUFError("Fichier GGUF tronqué")
    return b.decode("utf-8", "replace")


def _value(f, t: int, keep_arrays: bool = False):
    if t in _SCALARS:
        fmt, size = _SCALARS[t]
        return _read(f, fmt, size)
    if t == 8:
        return _string(f)
    if t == 9:
        et, n = _read(f, "<I", 4), _read(f, "<Q", 8)
        if n > 50_000_000:
            raise GGUFError("Tableau GGUF anormalement grand")
        if et in _SCALARS:
            size = _SCALARS[et][1]
            if keep_arrays and n <= 64:
                return [_value(f, et) for _ in range(n)]
            f.seek(n * size, 1)
        elif et == 8:
            for _ in range(n):  # jeton par jeton : les longueurs varient
                ln = _read(f, "<Q", 8)
                if ln > MAX_STR:
                    raise GGUFError("Chaîne GGUF anormalement longue")
                f.seek(ln, 1)
        else:
            raise GGUFError(f"Type de tableau GGUF non géré: {et}")
        return None
    raise GGUFError(f"Type GGUF inconnu: {t}")


def read_metadata(path: str | Path) -> tuple[int, int, dict]:
    p = Path(path)
    with p.open("rb") as f:
        if f.read(4) != MAGIC:
            raise GGUFError("Ce fichier n'est pas un GGUF (signature absente)")
        version = _read(f, "<I", 4)
        if version not in (2, 3):
            raise GGUFError(f"Version GGUF non prise en charge: {version}")
        tensors, kvs = _read(f, "<Q", 8), _read(f, "<Q", 8)
        if kvs > MAX_KV:
            raise GGUFError("Nombre de métadonnées anormal")
        meta: dict = {}
        for _ in range(kvs):
            key = _string(f)
            t = _read(f, "<I", 4)
            meta[key] = _value(f, t)
    return version, tensors, meta


def infer_capabilities(name: str, arch: str) -> list[str]:
    n = f"{name} {arch}".lower()
    caps = []
    if arch in ("bert", "nomic-bert", "jina-bert-v2"):
        return ["embedding"]
    caps.append("chat")
    if re.search(r"code|coder|starcoder|deepseek-coder", n):
        caps.append("code")
    if re.search(r"\bvl\b|vision|llava|moondream|minicpm-v|pixtral", n):
        caps.append("vision")
    if re.search(r"instruct|chat|-it\b", n) is None:
        caps.remove("chat")
        caps.append("base-model")
    return caps


def inspect(path: str | Path) -> GGUFInfo:
    p = Path(path)
    if p.suffix.lower() != ".gguf":
        raise GGUFError("Extension .gguf attendue")
    version, tensors, meta = read_metadata(p)
    arch = str(meta.get("general.architecture", "unknown"))
    g = lambda k: meta.get(f"{arch}.{k}")  # noqa: E731
    ft = meta.get("general.file_type")
    quant = FILE_TYPES.get(ft) if isinstance(ft, int) else None
    if not quant:
        m = _QUANT_RE.search(p.name)
        quant = m.group(1).upper() if m else "inconnue"
    name = str(meta.get("general.name") or p.stem)
    return GGUFInfo(path=str(p), file_name=p.name, size_bytes=p.stat().st_size, version=version,
                    tensor_count=tensors, architecture=arch, name=name, quantization=quant,
                    context_length=g("context_length"), block_count=g("block_count"),
                    embedding_length=g("embedding_length"), head_count=g("attention.head_count"),
                    head_count_kv=g("attention.head_count_kv"),
                    capabilities=infer_capabilities(f"{name} {p.stem}", arch))
