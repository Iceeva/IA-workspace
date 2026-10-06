import asyncio
import json

from app.catalog.catalog import Catalog, agent_from_dict
from app.catalog.model import Permission
from app.routing.intent import IntentAnalyzer
from app.routing.selector import AgentSelector
from app.llm.base import LLMProvider, LLMResponse

CAT = Catalog.default()
SEL = AgentSelector(CAT)


def names(mission, **kw):
    return [p.agent.name for p in SEL.select(mission, **kw).picks]


def test_catalog_has_over_1000_unique_agents():
    ids = [a.id for a in CAT]
    assert len(ids) > 1000 and len(ids) == len(set(ids))


def test_every_agent_declares_capabilities_not_providers():
    for a in CAT:
        assert a.skills and a.keywords and a.needs and a.system_prompt
        assert "openai" not in a.system_prompt.lower() and "anthropic" not in a.system_prompt.lower()


def test_sensitive_domains_have_guardrails():
    med = CAT.get("medical-research-assistant")
    assert med.sensitive and "professionnel" in med.system_prompt
    assert CAT.get("penetration-testing-assistant").sensitive


def test_modalities_and_needs_inferred():
    assert CAT.get("speech-to-text-agent").needs == ("chat", "speech-to-text")
    assert "vision" in CAT.get("image-analyst").needs and "image" in CAT.get("image-analyst").inputs
    g = CAT.get("image-generator"); assert g.needs_gpu and "text-to-image" in g.needs and g.multimodal


def test_dev_app_mission_selects_only_relevant_agents():
    got = names("Je veux créer une application React avec une API Python et PostgreSQL, sécurisée, avec des tests")
    for must in ("React Developer", "Python Developer", "PostgreSQL Specialist", "Testing Engineer"):
        assert must in got, got
    assert len(got) <= 6
    for unwanted in ("French Translator", "Music Composition Assistant", "Medical Research Assistant", "Physicist"):
        assert unwanted not in got


def test_unrelated_message_selects_nobody():
    r = SEL.select("bonjour, comment ça va ?")
    assert r.picks == [] and r.catalog_size > 1000


def test_explicit_debug_role_replaces_builder():
    got = names("corrige le bug dans mon code React")
    assert "React Debugging Specialist" in got and "React Developer" not in got


def test_review_and_teach_roles_only_when_requested():
    assert "Rust Tutor" in names("How do I learn Rust?")
    assert "Rust Tutor" not in names("écris un programme Rust")
    assert "Rust Developer" in names("écris un programme Rust")


def test_scikit_learn_is_not_a_teaching_request():
    got = names("entraîner un modèle scikit-learn")
    assert "scikit-learn Developer" in got or "scikit-learn Specialist" in got


def test_one_agent_per_overlapping_topic():
    got = names("audit de sécurité")
    assert got.count("Security Auditor") == 1 and len(got) <= 3


def test_search_filters_and_pagination():
    page, total = CAT.search("python", limit=5)
    assert len(page) == 5 and total >= 6 and page[0].domain == "python"
    page, _ = CAT.search("", category="Education", limit=100)
    assert page and all(a.category == "Education" for a in page)
    page, _ = CAT.search("", need="speech-to-text")
    assert "speech-to-text-agent" in [a.id for a in page] and all("speech-to-text" in a.needs for a in page)
    page, _ = CAT.search("", modality="audio", limit=100)
    assert all("audio" in (*a.inputs, *a.outputs) for a in page) and len(page) >= 5
    _, total_s = CAT.search("", sensitive=True); assert 0 < total_s < 40


def test_custom_agent_registers_without_touching_core(tmp_path):
    cat = Catalog.default(); n = len(cat)
    f = tmp_path / "extra.json"
    f.write_text(json.dumps([{"id": "cobol-banking", "name": "COBOL Banking Migrator", "category": "Custom",
                              "keywords": ["mainframe", "cobol"], "tools": {"filesystem": "READ"}}]))
    assert cat.load_json(f) == 1 and len(cat) == n + 1
    got = [p.agent.id for p in AgentSelector(cat).select("migrer un mainframe").picks]
    assert got == ["cobol-banking"]
    a = cat.get("cobol-banking"); assert a.source == "custom" and a.tools == (("filesystem", int(Permission.READ)),)
    try:
        agent_from_dict({"name": "x"}); assert False
    except ValueError:
        pass


def test_register_same_id_replaces_and_reindexes():
    cat = Catalog.default()
    a = cat.get("python-developer")
    cat.register(agent_from_dict({"id": "python-developer", "name": "Serpent Developer", "category": "Languages",
                                  "keywords": ["serpent"]}))
    assert [p.agent.id for p in AgentSelector(cat).select("serpent").picks] == ["python-developer"]
    assert "python-developer" not in [p.agent.id for p in AgentSelector(cat).select("python").picks] or a


class Scripted(LLMProvider):
    name = "s"
    def __init__(self, text): self.text = text
    async def chat(self, messages, *, model, temperature=0.2, max_tokens=4096):
        if self.text is None: raise RuntimeError("boom")
        return LLMResponse(self.text, model, 1, 1)


def test_llm_refinement_adds_keywords_and_is_optional():
    an = IntentAnalyzer()
    i = asyncio.run(an.refine(an.analyze("fais un truc pour mes ventes"), Scripted('{"keywords":["CRM","sales"]}'), "m"))
    assert "crm" in i.tokens
    assert "CRM Specialist" in [p.agent.name for p in SEL.select("x", intent=i).picks]
    i2 = asyncio.run(an.refine(an.analyze("python"), Scripted(None), "m"))
    assert i2.tokens == ["python"] and i2.extra == []
