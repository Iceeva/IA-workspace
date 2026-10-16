"""Rapport d'un Local Bridge au serveur (§19) : assainissement d'une donnée venue du navigateur, avant persistance.
Seuls des champs bornés et des adresses locales sont retenus ; clés API et chemins du disque sont écartés."""
from __future__ import annotations
import re

LOCAL = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?(/.*)?$")
KINDS = {"ollama", "lmstudio", "llamacpp", "localai", "vllm", "openai_compat", "phonon", "sana", "custom"}
STALE_AFTER_S = 120
MAX_RUNTIMES, MAX_MODELS = 20, 200


class ReportError(ValueError):
    pass


def _s(v, n: int) -> str:
    return str(v if v is not None else "")[:n]


def sanitize_report(payload: dict) -> list[dict]:
    items = payload.get("runtimes") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ReportError("« runtimes » doit être une liste")
    out, seen = [], set()
    for d in items[:MAX_RUNTIMES]:
        if not isinstance(d, dict):
            continue
        rid = _s(d.get("id"), 60).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", rid) or rid in seen:
            continue
        url = _s(d.get("base_url"), 200)
        if url and not LOCAL.match(url):
            continue                                          # un runtime « local » ne pointe jamais ailleurs
        seen.add(rid)
        kind = _s(d.get("kind"), 30)
        lat = d.get("latency_ms")
        out.append({"runtime_id": rid, "kind": kind if kind in KINDS else "custom", "name": _s(d.get("name") or rid, 80), "base_url": url,
                    "status": d.get("status") if d.get("status") in ("connected", "unreachable", "unknown") else "unknown",
                    "version": _s(d.get("version"), 40) or None,
                    "capabilities": sorted({_s(c, 30) for c in (d.get("capabilities") or [])[:20] if isinstance(c, str)}),
                    "models": [_s(m, 120) for m in (d.get("models") or [])[:MAX_MODELS] if isinstance(m, str)],
                    "latency_ms": int(lat) if isinstance(lat, (int, float)) and 0 <= lat < 10**7 else None})
    return out


def is_stale(age_s: float) -> bool:
    return age_s > STALE_AFTER_S


PERSIST_EVERY_S = 60


def fingerprint(items: list[dict]) -> str:
    """Empreinte stable d'un rapport : la latence varie à chaque détection, elle n'en fait pas partie."""
    import json
    return json.dumps([{k: v for k, v in i.items() if k != "latency_ms"} for i in items], sort_keys=True)


def persist_due(last: tuple[str, float] | None, fp: str, now: float, every_s: float = PERSIST_EVERY_S) -> bool:
    """Écrire en base seulement si le rapport a changé, ou pour rafraîchir `last_seen` toutes les `every_s` secondes."""
    return last is None or last[0] != fp or now - last[1] >= every_s
