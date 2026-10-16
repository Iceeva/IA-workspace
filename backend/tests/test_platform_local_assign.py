from app.services import local_assign as LA


def test_assign_adds_local_model_and_per_agent_entry_without_mutating_inputs():
    models0, pa0 = [{"id": "x:y", "caps": ["chat"]}], {"researcher": "cloud:big"}
    models, pa, key = LA.assign(models0, pa0, agent_id="python-developer", runtime_id="gguf-qwen3-8b", model="qwen3-8b", caps=["code"], context=8192)
    assert key == "bridge:gguf-qwen3-8b:qwen3-8b" and pa == {"researcher": "cloud:big", "python-developer": key}
    new = models[-1]
    assert new["id"] == "gguf-qwen3-8b:qwen3-8b" and new["local"] is True and new["caps"] == ["chat", "code"] and new["context"] == 8192 and new["cost_in"] == 0
    assert models0 == [{"id": "x:y", "caps": ["chat"]}] and pa0 == {"researcher": "cloud:big"}          # entrées intactes


def test_reassigning_replaces_the_model_entry_instead_of_duplicating():
    m1, pa, _ = LA.assign([], {}, agent_id="a", runtime_id="r", model="m", context=4096)
    m2, pa, _ = LA.assign(m1, pa, agent_id="b", runtime_id="r", model="m", context=16384)
    assert len(m2) == 1 and m2[0]["context"] == 16384 and set(pa) == {"a", "b"}


def test_assign_rejects_bad_identifiers_caps_and_context():
    for kw in ({"agent_id": "../x"}, {"runtime_id": "a b"}, {"model": ""}, {"model": "m;rm"}, {"caps": ["root"]}, {"context": 10}, {"context": 10**9}):
        args = {"agent_id": "a", "runtime_id": "r", "model": "m", **kw}
        try:
            LA.assign([], {}, **args); assert False, kw
        except LA.AssignError:
            pass


def test_unassign_and_listing():
    _, pa, key = LA.assign([], {"x": "cloud:big"}, agent_id="a", runtime_id="r", model="m")
    assert LA.local_assignments(pa) == [{"agent_id": "a", "runtime_id": "r", "model": "m", "key": key}]
    assert LA.unassign(pa, "a") == {"x": "cloud:big"}
    for bad in ("x", "zzz"):                      # agent sans modèle local (ou inconnu) : refusé, la config cloud n'est pas touchée
        try:
            LA.unassign(pa, bad); assert False
        except LA.AssignError:
            pass
    assert LA.local_assignments({}) == [] and LA.local_assignments(None) == []


def test_key_round_trips_through_the_router_registry():
    """La clé produite est celle que le registre de modèles construit pour le fournisseur « bridge »."""
    from app.routing.models import ModelInfo
    models, _, key = LA.assign([], {}, agent_id="a", runtime_id="gguf-q", model="q")
    m = ModelInfo(id=models[0]["id"], provider="bridge", caps=frozenset(models[0]["caps"]), local=True)
    assert m.key == key
