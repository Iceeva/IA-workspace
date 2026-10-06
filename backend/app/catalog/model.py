"""Définition d'un agent du catalogue (§5). Un agent déclare ce qu'il sait faire, jamais un fournisseur."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum


class Permission(IntEnum):
    """Niveaux d'accès d'un outil (§21). Ordonnés : un niveau accorde aussi les niveaux inférieurs."""
    NONE = 0
    READ = 1
    WRITE = 2
    EXECUTE = 3
    ADMIN = 4


class Modality(str, Enum):
    TEXT = "text"
    CODE = "code"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    DATA = "data"


# Rôle de l'agent vis-à-vis d'un sujet : sert à ne sélectionner que le bon agent (§4).
ROLE_KINDS = ("build", "specialist", "review", "debug", "test", "teach", "architect")


@dataclass(frozen=True)
class AgentDef:
    id: str
    name: str
    description: str
    category: str
    subcategory: str
    domain: str                              # sujet (ex. "react") ; un seul agent par domaine est retenu
    role_kind: str                           # build | review | debug | test | teach | specialist
    skills: tuple[str, ...]                  # étiquettes de compétence (ex. "code.python")
    keywords: tuple[str, ...]                # mots-clés normalisés, forte pondération
    needs: tuple[str, ...] = ("chat",)       # capacités requises du modèle/runtime (§5 « modèles compatibles »)
    tools: tuple[tuple[str, int], ...] = ()  # (outil, niveau Permission) autorisés
    inputs: tuple[str, ...] = ("text",)
    outputs: tuple[str, ...] = ("text",)
    permission_level: int = int(Permission.READ)
    est_tokens: int = 4000                   # consommation estimée par exécution
    min_ram_gb: float = 0.0                  # exigence matérielle si exécuté en local
    needs_gpu: bool = False
    local_ok: bool = True
    cloud_ok: bool = True
    sensitive: bool = False                  # domaines sensibles : garde-fous renforcés (§6)
    system_prompt: str = ""
    source: str = "builtin"                  # builtin | custom

    @property
    def multimodal(self) -> bool:
        return any(m not in ("text", "code") for m in (*self.inputs, *self.outputs))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tools"] = {n: Permission(p).name for n, p in self.tools}
        d["multimodal"] = self.multimodal
        return d
