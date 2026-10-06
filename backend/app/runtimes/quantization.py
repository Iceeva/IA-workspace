"""Quantization Studio (§30) : compromis taille / mémoire / vitesse / qualité.

ATTENTION : la quantification est une compression AVEC perte des poids du modèle. Elle n'a rien à voir avec la
compression sans perte des données (zstd, voir app/storage/cas.py). Les chiffres ci-dessous sont des ordres de
grandeur ; mesurez avec le module de benchmark sur votre machine avant de décider."""
from __future__ import annotations
from dataclasses import dataclass

# format → (bits par poids ≈, qualité relative indicative 0..1 par rapport à FP16)
FORMATS: dict[str, tuple[float, float]] = {
    "FP16": (16.0, 1.00), "FP8": (8.0, 0.985), "INT8": (8.0, 0.985), "Q8_0": (8.5, 0.995), "Q6_K": (6.56, 0.99),
    "Q5_K_M": (5.7, 0.98), "Q4_K_M": (4.9, 0.96), "Q4_0": (4.5, 0.93), "Q3_K_M": (3.9, 0.90), "Q2_K": (2.6, 0.78)}


@dataclass
class Row:
    fmt: str
    size_gb: float
    memory_gb: float            # poids + cache K/V + surcoût
    speed_x: float              # vitesse de génération relative à FP16 (modèle borné par la bande passante mémoire)
    quality: float              # indicatif
    fits_gpu: bool | None = None
    fits_ram: bool | None = None
    kind: str = "lossy"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compare(params_b: float, ctx: int = 4096, formats: list[str] | None = None, *, kv_bytes_per_token: int | None = None,
            vram_gb: float | None = None, ram_gb: float | None = None) -> list[Row]:
    """params_b : milliards de paramètres. Sans `kv_bytes_per_token`, le cache K/V est extrapolé d'un modèle 8B
    (≈ 128 Ko/token) proportionnellement au nombre de paramètres."""
    if params_b <= 0 or ctx <= 0:
        raise ValueError("params_b et ctx doivent être > 0")
    kv = (kv_bytes_per_token or int(131072 * params_b / 8)) * ctx / 1e9
    rows = []
    for f in formats or list(FORMATS):
        if f not in FORMATS:
            raise ValueError(f"Format inconnu: {f}")
        bpw, q = FORMATS[f]
        size = params_b * bpw / 8
        mem = round((size + kv) * 1.1 + 0.5, 2)
        rows.append(Row(f, round(size, 2), mem, round(16.0 / bpw, 2), q,
                        None if vram_gb is None else mem <= vram_gb, None if ram_gb is None else mem <= ram_gb))
    return rows


def best_fit(rows: list[Row]) -> Row | None:
    """Le format de meilleure qualité qui tient en VRAM, sinon en RAM."""
    for attr in ("fits_gpu", "fits_ram"):
        ok = [r for r in rows if getattr(r, attr)]
        if ok:
            return max(ok, key=lambda r: r.quality)
    return None
