"""Stockage adressable par contenu (§28, §29) : déduplication + compression sans perte + chiffrement.

Ordre : hash du contenu → compression → chiffrement (la compression avant le chiffrement conserve son efficacité).
Le hash est un HMAC par organisation : deux organisations qui stockent le même fichier ne partagent PAS la donnée
physique et ne peuvent pas détecter l'existence du fichier de l'autre. La déduplication joue au sein d'un périmètre.

Limites actuelles : pas de comptage de références ni de ramasse-miettes (aucune suppression physique), et le
module n'est pas encore branché sur l'API d'upload (voir docs/ROADMAP.md)."""
from __future__ import annotations
import hashlib
import hmac
import zlib
from dataclasses import dataclass

from app.core.crypto import CryptoError, SecretBox
from .backends import Storage

RAW, ZLIB, ZSTD = 0, 1, 2


class IntegrityError(RuntimeError):
    pass


def _zstd():
    try:
        import zstandard
        return zstandard
    except ImportError:
        return None


def compress(data: bytes) -> tuple[int, bytes]:
    """Meilleur codec disponible (zstd si installé, sinon zlib) ; données incompressibles stockées telles quelles."""
    z = _zstd()
    codec, out = (ZSTD, z.ZstdCompressor(level=6).compress(data)) if z else (ZLIB, zlib.compress(data, 6))
    return (codec, out) if len(out) < len(data) else (RAW, data)


def decompress(codec: int, blob: bytes, max_size: int = 1 << 31) -> bytes:
    if codec == RAW:
        return blob
    if codec == ZLIB:
        d = zlib.decompressobj()
        out = d.decompress(blob, max_size)
        if d.unconsumed_tail:
            raise IntegrityError("Taille décompressée excessive")
        return out
    if codec == ZSTD:
        z = _zstd()
        if z is None:
            raise IntegrityError("Objet compressé en zstd : installez le paquet 'zstandard'")
        return z.ZstdDecompressor().decompress(blob, max_output_size=max_size)
    raise IntegrityError(f"Codec inconnu: {codec}")


@dataclass(frozen=True)
class CasResult:
    hash: str
    size: int
    stored_size: int
    deduplicated: bool
    codec: int


class ContentStore:
    def __init__(self, backend: Storage, box: SecretBox | None, scope: str):
        self.backend, self.box = backend, box
        self._hkey = box.derive_scope_key(scope) if box else hashlib.sha256(b"aiw/cas-plain|" + scope.encode()).digest()

    def digest(self, data: bytes) -> str:
        return hmac.new(self._hkey, data, hashlib.sha256).hexdigest()

    @staticmethod
    def key_for(h: str) -> str:
        return f"cas/{h[:2]}/{h[2:]}"

    async def put(self, data: bytes) -> CasResult:
        h = self.digest(data)
        key = self.key_for(h)
        codec, body = compress(data)
        payload = bytes([codec]) + body
        if await self.backend.exists(key):
            return CasResult(h, len(data), 0, True, codec)
        blob = b"E" + self.box.encrypt_bytes(payload, h.encode()) if self.box else b"P" + payload
        await self.backend.put(key, blob, "application/octet-stream")
        return CasResult(h, len(data), len(blob), False, codec)

    async def get(self, h: str) -> bytes:
        blob = await self.backend.get(self.key_for(h))
        try:
            if blob[:1] == b"E":
                if not self.box:
                    raise IntegrityError("Objet chiffré : clé de chiffrement requise")
                payload = self.box.decrypt_bytes(blob[1:], h.encode())
            elif blob[:1] == b"P":
                payload = blob[1:]
            else:
                raise IntegrityError("Format d'objet inconnu")
        except CryptoError as e:
            raise IntegrityError(str(e)) from e
        data = decompress(payload[0], payload[1:])
        if not hmac.compare_digest(self.digest(data), h):  # restauration exacte, sans corruption
            raise IntegrityError("Le contenu restauré ne correspond pas à son empreinte")
        return data
