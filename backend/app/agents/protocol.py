"""Protocole de communication entre agents (§38).

Un agent peut glisser dans sa réponse des blocs ```aiw-msg {json}``` pour : transmettre un résultat, demander une
information, demander une analyse, demander l'intervention d'un autre agent, signaler une erreur, demander une validation
ou terminer. Les blocs sont retirés du texte livré aux humains ; toutes les communications sont journalisées pour
pouvoir reconstruire l'exécution. Le contenu est une DONNÉE produite par un modèle : il est validé, borné, jamais exécuté."""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum


class MsgType(str, Enum):
    RESULT = "result"
    REQUEST_INFO = "request_info"
    REQUEST_ANALYSIS = "request_analysis"
    REQUEST_AGENT = "request_agent"
    ERROR = "error"
    REQUEST_VALIDATION = "request_validation"
    DONE = "done"


# types qui demandent le travail d'un autre agent (déclenchent une replanification)
DELEGATING = {MsgType.REQUEST_AGENT, MsgType.REQUEST_ANALYSIS}
MAX_PER_REPLY, MAX_CONTENT = 5, 4000
_BLOCK = re.compile(r"```aiw-msg\s*(\{.*?\})\s*```", re.S)


@dataclass
class AgentMessage:
    type: MsgType
    sender: str
    recipient: str = ""          # agent visé (id) ; vide = orchestrateur
    content: str = ""
    ref: str = ""                # tâche concernée
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"type": self.type.value, "sender": self.sender, "recipient": self.recipient,
                "content": self.content, "ref": self.ref, "ts": self.ts}


def parse_messages(text: str, sender: str, ref: str = "") -> tuple[str, list[AgentMessage]]:
    """Retourne (texte sans les blocs, messages valides). Les blocs invalides sont ignorés, jamais fatals."""
    msgs: list[AgentMessage] = []
    for m in _BLOCK.finditer(text or ""):
        if len(msgs) >= MAX_PER_REPLY:
            break
        try:
            d = json.loads(m.group(1))
            t = MsgType(str(d["type"]))
        except (ValueError, KeyError, TypeError):
            continue
        rcpt = d.get("agent") or d.get("recipient") or ""
        if not isinstance(rcpt, str) or len(rcpt) > 80 or not re.fullmatch(r"[A-Za-z0-9_.-]*", rcpt):
            continue
        content = str(d.get("content") or d.get("reason") or "")[:MAX_CONTENT]
        msgs.append(AgentMessage(t, sender, rcpt, content, ref))
    return _BLOCK.sub("", text or "").strip(), msgs


def protocol_instructions(agent_ids: list[str]) -> str:
    ids = ", ".join(agent_ids[:30]) or "(aucun)"
    return ("\n\nSi tu découvres qu'une compétence supplémentaire est nécessaire, tu peux le signaler avec un bloc :\n"
            '```aiw-msg\n{"type": "request_agent", "agent": "<id>", "reason": "<pourquoi>"}\n```\n'
            "Types : request_agent, request_analysis, request_info, request_validation, error, done. "
            f"Agents demandables : {ids}. N'en demande que si c'est indispensable.")


class MessageLog:
    """Journal ordonné des communications ; permet de reconstruire qui a demandé quoi à qui."""

    def __init__(self) -> None:
        self.items: list[AgentMessage] = []

    def add(self, m: AgentMessage) -> None:
        self.items.append(m)

    def thread(self, task_id: str) -> list[dict]:
        return [m.to_dict() for m in self.items if m.ref == task_id]

    def between(self, a: str, b: str) -> list[dict]:
        return [m.to_dict() for m in self.items if {m.sender, m.recipient} == {a, b}]

    def to_list(self) -> list[dict]:
        return [m.to_dict() for m in self.items]

    def delegation_chain(self) -> list[tuple[str, str]]:
        return [(m.sender, m.recipient) for m in self.items if m.type in DELEGATING and m.recipient]
