"""Validation des URL de fournisseurs saisies par l'utilisateur (anti-SSRF : le serveur appellera cette URL).

Limite connue : une résolution DNS vérifiée à l'enregistrement ne protège pas contre un « DNS rebinding » au moment
de l'appel. En production multi-tenant, ajoutez une restriction réseau côté infrastructure (egress filtré)."""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlsplit


def validate_provider_url(url: str, *, allow_private: bool = False, resolver=socket.getaddrinfo) -> str:
    u = urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("URL invalide : http(s)://hôte[:port]/chemin attendu")
    if u.username or u.password:
        raise ValueError("Les identifiants dans l'URL sont interdits (utilisez le champ clé API)")
    if not allow_private:
        if u.scheme != "https":
            raise ValueError("HTTPS obligatoire pour un fournisseur distant")
        try:
            infos = resolver(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
        except OSError as e:
            raise ValueError(f"Hôte introuvable : {u.hostname}") from e
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise ValueError("Adresse privée ou locale interdite pour un fournisseur distant "
                                 "(réservé aux installations locales : ALLOW_PRIVATE_PROVIDER_URLS=true)")
    return url.strip().rstrip("/")
