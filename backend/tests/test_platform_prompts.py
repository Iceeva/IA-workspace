import re

from app.catalog import taxonomy as T
from app.catalog.prompt_specialists import SPECIALISTS
from app.catalog.prompt_stacks import STACKS
from app.catalog.taxonomy import build_default_catalog

CAT = build_default_catalog()


def test_every_agent_has_a_structured_prompt_of_reasonable_size():
    assert len(CAT) >= 1000
    for a in CAT:
        p = a.system_prompt
        assert a.name in p and all(h in p for h in ("# Identité", "# Méthode", "# Livrable", "# Règles")), a.id
        assert 900 <= len(p) <= 3500, (a.id, len(p))                       # utile mais pas gaspilleur de tokens
        assert not re.search(r"TODO|XXX|\{[a-z_]+\}", p), a.id


def test_prompts_are_all_distinct_and_specific_to_the_topic():
    assert len({a.system_prompt for a in CAT}) == len(CAT)
    py = next(a for a in CAT if a.id == "python-developer").system_prompt
    assert "mypy" in py and "arguments par défaut mutables" in py
    k8s = next(a for a in CAT if a.id == "kubernetes-architect").system_prompt
    assert "NetworkPolicies" in k8s and "mypy" not in k8s


def test_knowledge_tables_cover_the_whole_taxonomy_exactly():
    specs = {n for v in T._SPECIALISTS.values() for n in v.split(";")}
    stacks = {i.partition("|")[0] for _, raw, _ in T._STACKS for i in raw.split(";")}
    assert specs == set(SPECIALISTS) and stacks == set(STACKS)


def test_role_specific_methods():
    tests = [a for a in CAT if a.role_kind == "test" or a.name == "Testing Engineer"]
    assert tests and all("VERDICT: PASS" in a.system_prompt and "VERDICT: FAIL" in a.system_prompt for a in tests)
    assert all("VERDICT" not in a.system_prompt for a in CAT if a.role_kind in ("build", "review", "debug", "teach", "architect"))
    assert all("BLOQUANT" in a.system_prompt for a in CAT if a.role_kind == "review")
    assert all("cause racine" in a.system_prompt for a in CAT if a.role_kind == "debug")


def test_guards_for_sensitive_and_security_domains():
    for a in CAT:
        if a.category in ("Health", "Legal & Finance"):
            assert "Garde-fous" in a.system_prompt and "professionnel" in a.system_prompt, a.id
    pen = next(a for a in CAT if a.name == "Penetration Testing Assistant").system_prompt
    assert "autorisation" in pen and "# Garde-fous" in pen
    med = next(a for a in CAT if a.name == "Medical Document Analyzer").system_prompt
    assert "diagnostic" in med.lower() or "médecin" in med


def test_tool_hints_follow_granted_level():
    dev = next(a for a in CAT if a.id == "python-developer").system_prompt          # filesystem WRITE + terminal
    assert "ne modifie que les fichiers nécessaires" in dev and "conteneur isolé" in dev
    rev = next(a for a in CAT if a.id == "python-code-reviewer").system_prompt      # lecture seule
    assert "lecture seule" in rev and "ne modifie que" not in rev and "conteneur isolé" not in rev
    assert "# Outils" not in next(a for a in CAT if a.name == "French Translator").system_prompt
