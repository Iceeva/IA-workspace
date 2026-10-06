from __future__ import annotations
from app.llm.base import LLMProvider
from .base import BaseAgent

_ROLES: dict[str, tuple[str, str, float]] = {
    "planner": ("Planner", "Décompose une mission en tâches ordonnées avec dépendances. "
                "Réponds UNIQUEMENT en JSON: {\"tasks\":[{\"id\":str,\"title\":str,\"agent\":str,\"depends_on\":[str]}]}. "
                "Agents autorisés: researcher, architect, coder, tester, reviewer.", 0.1),
    "researcher": ("Researcher", "Tu analyses le besoin, listes hypothèses, risques et références utiles.", 0.3),
    "architect": ("Architect", "Tu conçois l'architecture: composants, modèles de données, contrats d'API.", 0.2),
    "coder": ("Coder", "Tu écris du code complet et exécutable. Un bloc par fichier, au format exact : ```<langage> path=<chemin/relatif>``` puis le code, puis ```.", 0.1),
    "tester": ("Tester", "Tu écris et évalues des tests. Termine par une ligne 'VERDICT: PASS' ou 'VERDICT: FAIL' "
               "suivie des erreurs.", 0.0),
    "debugger": ("Debugger", "Tu analyses les erreurs de test et fournis le code corrigé.", 0.1),
    "reviewer": ("Reviewer", "Tu relis l'ensemble: correction, sécurité, lisibilité. Termine par un résumé final.", 0.2),
}
ROLES = tuple(_ROLES)


def build_agent(role: str, provider: LLMProvider, model: str, *, system_prompt: str | None = None,
                temperature: float | None = None) -> BaseAgent:
    if role not in _ROLES:
        raise ValueError(f"Rôle inconnu: {role}")
    title, prompt, temp = _ROLES[role]
    return BaseAgent(name=title, role=role, description=prompt.split(".")[0], model=model, provider=provider,
                     system_prompt=system_prompt or f"Tu es {title}. {prompt}",
                     temperature=temp if temperature is None else temperature)
