"""Observabilité (§41) : reconstruit « comment la réponse a été produite » à partir du journal d'événements d'une exécution.

Fonction pure (liste d'événements → structure) : quel agent a été appelé, pourquoi il a été retenu, quel modèle a répondu
(et les bascules de fournisseur), quels outils il a utilisés, durée, tokens, résultat, et quel agent a été appelé ensuite."""
from __future__ import annotations

OUT_MAX = 600


def build_trace(events: list[dict]) -> dict:
    """events : [{seq, kind, data}] triés par seq. Tolérant aux journaux incomplets (exécution en cours)."""
    picks: dict[str, dict] = {}
    selection: dict = {}
    tasks: dict[str, dict] = {}
    order: list[str] = []
    fallbacks: list[dict] = []
    replans: list[dict] = []
    plan_source, plan_note = None, None
    current: str | None = None            # dernière tâche démarrée : les bascules lui sont attribuées (approximation si tâches parallèles)

    def task(tid: str) -> dict:
        if tid not in tasks:
            tasks[tid] = {"id": tid, "title": "", "agent": "", "status": "PENDING", "depends_on": [], "next": [], "why": "",
                          "model": "", "tools": [], "tokens_in": 0, "tokens_out": 0, "tokens": 0, "duration_ms": 0,
                          "error": None, "output": "", "fallbacks": [], "requested_by": None, "started_seq": None}
            order.append(tid)
        return tasks[tid]

    for ev in events:
        k, d, seq = ev.get("kind", ""), ev.get("data") or {}, ev.get("seq")
        if k == "agents.selected":
            selection = {"considered": d.get("considered"), "catalog_size": d.get("catalog_size"), "agents": d.get("agents", [])}
            picks = {a.get("id"): a for a in d.get("agents", [])} | {a.get("name"): a for a in d.get("agents", [])}
        elif k == "plan.created":
            plan_source = d.get("source")
        elif k == "plan.fallback":
            plan_note = d.get("reason")
        elif k == "graph":
            for n in d.get("nodes", []):
                t = task(n["id"])
                t.update(title=n.get("title", ""), agent=n.get("agent", ""), depends_on=list(n.get("depends_on", [])))
        elif k == "plan.replanned":
            n = d.get("added", {})
            if n.get("id"):
                t = task(n["id"])
                t.update(title=n.get("title", ""), agent=n.get("agent", ""), depends_on=list(n.get("depends_on", [])),
                         requested_by=d.get("requested_by"))
                replans.append({"task": n["id"], "agent": n.get("agent"), "requested_by": d.get("requested_by"), "reason": d.get("reason", "")[:300]})
        elif k == "model.fallback":
            fb = {"used": d.get("used"), "failed": d.get("failed", [])}
            fallbacks.append(fb)
            if current:
                tasks[current]["fallbacks"].append(fb)
        elif k == "model.failed":
            fb = {"failed": [d.get("target")], "error": d.get("error", "")[:160]}
            fallbacks.append(fb)
            if current:
                tasks[current]["fallbacks"].append(fb)
        elif k == "task.started":
            t = task(d["id"])
            t.update(status="RUNNING", title=d.get("title", t["title"]), agent=d.get("agent", t["agent"]), started_seq=seq)
            current = d["id"]
        elif k == "task.trace":
            t = task(d["id"])
            t.update(model=d.get("model", ""), tools=d.get("tools", []), tokens_in=d.get("tokens_in", 0), tokens_out=d.get("tokens_out", 0))
        elif k in ("task.completed", "task.failed", "task.review_required"):
            t = task(d["id"])
            t.update(status=d.get("status", t["status"]), tokens=d.get("tokens", 0), duration_ms=d.get("duration_ms", 0), error=d.get("error"),
                     model=d.get("model") or t["model"])
        elif k == "task.output":
            task(d["id"])["output"] = str(d.get("output", ""))[:OUT_MAX]

    for t in tasks.values():
        for dep in t["depends_on"]:
            if dep in tasks and t["id"] not in tasks[dep]["next"]:
                tasks[dep]["next"].append(t["id"])
        p = picks.get(t["agent"])
        if t["requested_by"]:
            t["why"] = f"Demandé en cours d'exécution par « {t['requested_by']} »"
        elif p:
            t["why"] = f"Retenu parmi {selection.get('catalog_size', '?')} agents : {p.get('reason', '')} (score {p.get('score')})".strip()
        else:
            t["why"] = "Rôle standard du plan" if plan_source != "workflow" else "Nœud défini dans le workflow"
    steps = sorted((tasks[i] for i in order), key=lambda t: (t["started_seq"] is None, t["started_seq"] or 0))
    return {"plan_source": plan_source, "plan_note": plan_note, "selection": selection, "replans": replans,
            "fallbacks": fallbacks, "steps": steps,
            "totals": {"tokens_in": sum(t["tokens_in"] for t in steps), "tokens_out": sum(t["tokens_out"] for t in steps),
                       "duration_ms": sum(t["duration_ms"] for t in steps),
                       "tool_calls": sum(len(t["tools"]) for t in steps)}}
