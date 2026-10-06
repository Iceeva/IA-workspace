"""Normalisation de texte pour l'indexation et l'analyse d'intention (FR/EN, sans dépendance)."""
from __future__ import annotations
import re
import unicodedata

_PHRASES = (("scikit-learn", "sklearn"), ("scikit learn", "sklearn"), ("c++", "cpp"), ("c#", "csharp"), ("f#", "fsharp"), ("node.js", "nodejs"), ("next.js", "nextjs"),
            ("nuxt.js", "nuxt"), ("vue.js", "vue"), ("three.js", "threejs"), ("express.js", "express"),
            (".net", "dotnet"), ("base de donnees", "database"), ("bases de donnees", "database"),
            ("machine learning", "ml"), ("deep learning", "ml"), ("front-end", "frontend"),
            ("back-end", "backend"), ("full-stack", "fullstack"), ("full stack", "fullstack"),
            ("open source", "opensource"), ("speech to text", "stt"), ("text to speech", "tts"))
# Préfixes → forme canonique. Permet « sécurisée »/« security », « corriger »/« debug », etc.
_PREFIX = (("securi", "security"), ("secur", "security"), ("donnee", "data"), ("recherch", "research"),
           ("tradu", "translation"), ("translat", "translation"), ("medic", "medical"), ("juridi", "legal"),
           ("deploi", "deployment"), ("deploy", "deployment"), ("apprend", "learn"), ("explique", "explain"),
           ("corrig", "debug"), ("debug", "debug"), ("erreur", "bug"), ("revue", "review"), ("relire", "review"),
           ("relec", "review"), ("audit", "audit"), ("testing", "test"), ("tester", "test"), ("test", "test"),
           ("architect", "architecture"), ("review", "review"), ("contrat", "contract"), ("musiq", "music"), ("sante", "health"), ("optimis", "optimization"), ("optimiz", "optimization"),
           ("transcri", "stt"), ("vocal", "speech"), ("voix", "speech"), ("finance", "finance"),
           ("financi", "finance"), ("marketing", "marketing"), ("redig", "writing"), ("ecrire", "writing"),
           ("document", "document"), ("resum", "summarize"), ("summariz", "summarize"))
GENERIC = frozenset("""a an the and or of for to in on with de la le les des du un une et ou pour avec sur dans par
un une mon ma mes que qui je tu il nous vous veux voudrais besoin cree creer faire fait fais peux peut
developer engineer specialist agent assistant analyst expert i want need make build create help me my please
s est sont etre avoir code mon ton son ce cet cette ces comment quoi""".split())
_TOKEN = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for a, b in _PHRASES:
        t = t.replace(a, f" {b} ")
    return t


def _canon(tok: str) -> str:
    for p, c in _PREFIX:
        if tok.startswith(p):
            return c
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        tok = tok[:-1]
    return tok


def tokens(text: str, *, keep_generic: bool = False) -> list[str]:
    out = []
    for raw in _TOKEN.findall(normalize(text)):
        if raw in GENERIC and not keep_generic:
            continue
        out.append(_canon(raw))
    return out
