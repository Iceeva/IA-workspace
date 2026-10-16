"""Attribuer un modèle local (ex. un GGUF servi par le Local Bridge) à UN agent (§9 mode 2, §11).

Partie pure (testable sans base) : on prépare la liste de modèles du fournisseur « bridge » et la table `per_agent` des
préférences. Le fournisseur de type bridge route vers le bridge de l'utilisateur qui exécute la mission."""
from __future__ import annotations
import re

PROVIDER_NAME = "bridge"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
CAPS = {"chat", "code", "vision", "embedding", "long-context", "reasoning"}
CTX_RANGE = (256, 262144)


class AssignError(ValueError):
    pass


def model_key(runtime_id: str, model: str) -> str:
    """Clé de routage complète : « bridge:<runtime>:<modèle> »."""
    return f"{PROVIDER_NAME}:{runtime_id}:{model}"


def assign(models: list[dict], per_agent: dict, *, agent_id: str, runtime_id: str, model: str, caps: list[str] | None = None,
           context: int = 4096) -> tuple[list[dict], dict, str]:
    """→ (modèles du fournisseur bridge, per_agent mis à jour, clé de routage). N'altère pas les entrées."""
    for label, v in (("agent", agent_id), ("runtime", runtime_id), ("modèle", model)):
        if not isinstance(v, str) or not ID_RE.match(v):
            raise AssignError(f"Identifiant de {label} invalide")
    caps = sorted(set(caps or ["chat"]))
    if not set(caps) <= CAPS:
        raise AssignError("Capacité inconnue : " + ", ".join(sorted(set(caps) - CAPS)))
    if "chat" not in caps:
        caps.append("chat")
    if not CTX_RANGE[0] <= context <= CTX_RANGE[1]:
        raise AssignError(f"Contexte hors limites ({CTX_RANGE[0]}–{CTX_RANGE[1]})")
    mid = f"{runtime_id}:{model}"
    entry = {"id": mid, "caps": sorted(caps), "quality": 0.5, "speed": 0.5, "cost_in": 0.0, "cost_out": 0.0, "context": context, "local": True}
    out = [m for m in models if m.get("id") != mid] + [entry]              # remplace l'entrée existante (contexte à jour)
    pa = dict(per_agent or {})
    pa[agent_id] = model_key(runtime_id, model)
    return out, pa, pa[agent_id]


def unassign(per_agent: dict, agent_id: str) -> dict:
    pa = dict(per_agent or {})
    if not pa.get(agent_id, "").startswith(PROVIDER_NAME + ":"):
        raise AssignError("Cet agent n'a pas de modèle local attribué")
    pa.pop(agent_id)
    return pa


def local_assignments(per_agent: dict) -> list[dict]:
    out = []
    for agent, key in sorted((per_agent or {}).items()):
        if isinstance(key, str) and key.startswith(PROVIDER_NAME + ":"):
            rid, _, model = key[len(PROVIDER_NAME) + 1:].partition(":")
            out.append({"agent_id": agent, "runtime_id": rid, "model": model, "key": key})
    return out
