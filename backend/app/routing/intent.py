"""Analyse d'intention (§3, §45) : heuristique locale, rapide et sans appel modèle ; raffinement LLM optionnel."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

from app.catalog.text import tokens

# Mots (déjà canonisés par catalog.text) qui déclenchent un rôle explicite.
ROLE_TRIGGERS = {"review": {"review"}, "debug": {"debug", "bug", "crash"}, "test": {"test"},
                 "teach": {"learn", "explain", "course", "cours", "tutor", "teach", "tutorial"},
                 "architect": {"architecture"}}
CREATE_WORDS = {"creer", "cree", "create", "build", "write", "ecrire", "ecris", "implement", "implemente",
                "develop", "developpe", "developper", "developpement", "make", "fais", "genere", "generate",
                "app", "application", "site", "projet", "project", "construire"}


@dataclass
class Intent:
    text: str
    tokens: list[str]
    roles: set[str] = field(default_factory=set)   # rôles explicitement demandés (review, debug, ...)
    creation: bool = False                         # la demande vise la production d'un livrable
    extra: list[str] = field(default_factory=list) # mots ajoutés par le raffinement LLM


class IntentAnalyzer:
    def analyze(self, text: str) -> Intent:
        raw = set(tokens(text, keep_generic=True))
        toks = tokens(text)
        roles = {r for r, trig in ROLE_TRIGGERS.items() if raw & trig}
        return Intent(text=text, tokens=toks, roles=roles, creation=bool(raw & CREATE_WORDS))

    async def refine(self, intent: Intent, provider, model: str) -> Intent:
        """Demande à un modèle des mots-clés supplémentaires (synonymes, termes techniques implicites).
        En cas d'erreur ou de réponse invalide, l'intention heuristique est conservée telle quelle."""
        from app.llm.base import Message
        try:
            r = await provider.chat([
                Message("system", "Réponds UNIQUEMENT en JSON: {\"keywords\":[mots-clés techniques en anglais]}. "
                                  "Pas plus de 8 mots-clés."),
                Message("user", f"Demande: {intent.text[:2000]}")], model=model, temperature=0.0, max_tokens=200)
            m = re.search(r"\{.*\}", r.content, re.S)
            kws = json.loads(m.group(0))["keywords"] if m else []
            extra = [t for k in kws[:8] if isinstance(k, str) for t in tokens(k)]
        except Exception:  # noqa: BLE001 — le raffinement est facultatif
            return intent
        intent.extra = extra
        intent.tokens = list(dict.fromkeys([*intent.tokens, *extra]))
        return intent
