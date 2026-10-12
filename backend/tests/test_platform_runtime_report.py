from app.runtimes.report import ReportError, is_stale, sanitize_report


def test_report_keeps_only_local_bounded_fields_and_drops_secrets():
    r = sanitize_report({"runtimes": [
        {"id": "ollama", "kind": "ollama", "name": "Ollama", "base_url": "http://127.0.0.1:11434", "status": "connected",
         "models": ["qwen3:8b", 5, "x" * 500], "capabilities": ["chat", "code", 3], "latency_ms": 12,
         "requirements": {"api_key": "sk-secret"}, "api_key": "sk-secret", "path": "/home/u/models"},
        {"id": "evil", "kind": "custom", "base_url": "http://10.0.0.5:9"},                   # adresse non locale : écarté
        {"id": "bad id!", "base_url": "http://localhost:1"},                                  # identifiant invalide : écarté
        {"id": "ollama", "base_url": "http://localhost:1"},                                   # doublon : écarté
        {"id": "weird", "kind": "rootkit", "status": "hacked", "latency_ms": -4},
        "pas un dict"]})
    assert [x["runtime_id"] for x in r] == ["ollama", "weird"]
    o, w = r
    assert o["models"][0] == "qwen3:8b" and len(o["models"]) == 2 and len(o["models"][1]) == 120 and o["capabilities"] == ["chat", "code"]
    assert "sk-secret" not in repr(r) and "/home/u" not in repr(r)
    assert w["kind"] == "custom" and w["status"] == "unknown" and w["latency_ms"] is None and w["base_url"] == ""


def test_report_rejects_non_list_and_caps_size():
    for bad in ({}, {"runtimes": "x"}, [], None):
        try:
            sanitize_report(bad); assert False
        except ReportError:
            pass
    assert len(sanitize_report({"runtimes": [{"id": f"r{i}"} for i in range(100)]})) == 20


def test_staleness_threshold():
    assert not is_stale(60) and is_stale(121)
