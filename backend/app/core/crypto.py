"""Chiffrement des secrets (clés API des fournisseurs, §8) et des objets stockés (§28). AES-256-GCM.

Rotation : ENCRYPTION_KEY peut contenir plusieurs clés séparées par des virgules ; la première chiffre,
toutes déchiffrent. Sans ENCRYPTION_KEY, une clé est dérivée de JWT_SECRET (pratique en développement,
déconseillé en production : changer JWT_SECRET rendrait les secrets illisibles)."""
from __future__ import annotations
import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "enc:v1:"


class CryptoError(ValueError):
    pass


def _key(secret: str) -> bytes:
    return hashlib.sha256(b"aiw/secretbox/v1|" + secret.encode()).digest()


class SecretBox:
    def __init__(self, secrets: list[str]):
        secrets = [s.strip() for s in secrets if s and s.strip()]
        if not secrets:
            raise CryptoError("Aucune clé de chiffrement configurée")
        if any(len(s) < 16 for s in secrets):
            raise CryptoError("Clé de chiffrement trop courte (16 caractères minimum)")
        self._keys = [_key(s) for s in secrets]

    def encrypt_bytes(self, data: bytes, aad: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._keys[0]).encrypt(nonce, data, aad)

    def decrypt_bytes(self, blob: bytes, aad: bytes = b"") -> bytes:
        if len(blob) < 28:
            raise CryptoError("Données chiffrées invalides")
        nonce, ct = blob[:12], blob[12:]
        for k in self._keys:
            try:
                return AESGCM(k).decrypt(nonce, ct, aad)
            except InvalidTag:
                continue
        raise CryptoError("Déchiffrement impossible (clé incorrecte ou données altérées)")

    def encrypt(self, text: str, aad: str = "") -> str:
        return PREFIX + base64.urlsafe_b64encode(self.encrypt_bytes(text.encode(), aad.encode())).decode()

    def decrypt(self, token: str, aad: str = "") -> str:
        if not token.startswith(PREFIX):
            raise CryptoError("Format de secret inconnu")
        try:
            blob = base64.urlsafe_b64decode(token[len(PREFIX):].encode())
        except ValueError as e:
            raise CryptoError("Secret illisible") from e
        return self.decrypt_bytes(blob, aad.encode()).decode()

    def derive_scope_key(self, scope: str) -> bytes:
        """Clé HMAC propre à un périmètre (organisation) : sert à la déduplication sans fuite inter-tenants."""
        return hmac.new(self._keys[0], b"aiw/cas-scope|" + scope.encode(), hashlib.sha256).digest()


def mask(secret: str | None) -> str:
    """Affichage sûr d'une clé : jamais plus de 4 derniers caractères, jamais pour les clés courtes."""
    if not secret:
        return ""
    return "••••" + secret[-4:] if len(secret) >= 12 else "••••"


def get_secretbox() -> SecretBox:
    from .config import get_settings
    s = get_settings()
    return SecretBox((s.encryption_key.split(",") if s.encryption_key else [s.jwt_secret]))
