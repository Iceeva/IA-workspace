"""Déclencheurs (§26) : cron, signature de webhook, correspondance d'événements. Logique pure."""
from __future__ import annotations
import fnmatch
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

TRIGGER_TYPES = ("manual", "webhook", "schedule", "file_added", "github", "api_event", "agent_event", "db_event")
REPLAY_WINDOW_S = 300


class CronError(ValueError):
    pass


_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12, "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _field(text: str, lo: int, hi: int, is_dow: bool = False) -> set[int]:
    out: set[int] = set()
    for part in text.lower().split(","):
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.isdigit() or int(s) < 1:
                raise CronError(f"Pas invalide : {s}")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (_val(x, is_dow) for x in part.split("-", 1))
        else:
            a = _val(part, is_dow)
            b = hi if step > 1 else a
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise CronError(f"Valeur hors limites : {part}")
        out.update(range(a, b + 1, step))
    return {x % 7 for x in out} if is_dow else out


def _val(x: str, is_dow: bool) -> int:
    if x in _NAMES:
        return _NAMES[x]
    if x.isdigit():
        return int(x)
    raise CronError(f"Valeur invalide : {x}")


def parse_cron(expr: str):
    parts = expr.split()
    if len(parts) != 5:
        raise CronError("Expression cron : 5 champs attendus (minute heure jour mois jour-semaine)")
    sets = [_field(p, lo, hi, i == 4) for i, (p, (lo, hi)) in enumerate(zip(parts, _RANGES))]
    return sets, parts[2] != "*", parts[4] != "*"


def next_run(expr: str, after: datetime) -> datetime:
    """Prochaine échéance strictement postérieure à `after` (UTC), sur 5 ans maximum."""
    (mins, hours, doms, months, dows), dom_r, dow_r = parse_cron(expr)
    t = (after.astimezone(timezone.utc) if after.tzinfo else after.replace(tzinfo=timezone.utc))
    t = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=366 * 5)
    while t < limit:
        if t.month not in months:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        dow = (t.weekday() + 1) % 7
        day_ok = (t.day in doms or dow in dows) if (dom_r and dow_r) else (t.day in doms and dow in dows)
        if not day_ok:
            t = t.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if t.hour not in hours:
            t = t.replace(minute=0) + timedelta(hours=1)
            continue
        if t.minute not in mins:
            t += timedelta(minutes=1)
            continue
        return t
    raise CronError("Aucune échéance dans les 5 ans")


def sign_webhook(secret: str, body: bytes, ts: int | None = None) -> tuple[str, str]:
    """Signature AI Workspace : HMAC-SHA256 de « timestamp.corps ». Retourne (timestamp, signature)."""
    ts_s = str(ts if ts is not None else int(time.time()))
    mac = hmac.new(secret.encode(), ts_s.encode() + b"." + body, hashlib.sha256).hexdigest()
    return ts_s, "sha256=" + mac


def verify_webhook(secret: str, body: bytes, ts: str | None, signature: str | None, now: float | None = None) -> bool:
    if not ts or not signature or not ts.isdigit():
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > REPLAY_WINDOW_S:
        return False  # rejeu
    return hmac.compare_digest(sign_webhook(secret, body, int(ts))[1], signature)


def verify_github(secret: str, body: bytes, signature: str | None) -> bool:
    """En-tête X-Hub-Signature-256 de GitHub : « sha256=HMAC(secret, corps) »."""
    if not signature or not signature.startswith("sha256="):
        return False
    return hmac.compare_digest("sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), signature)


def _match(filter_value, actual) -> bool:
    if isinstance(filter_value, list):
        return any(_match(f, actual) for f in filter_value)
    if isinstance(filter_value, str) and isinstance(actual, str):
        return fnmatch.fnmatchcase(actual, filter_value)
    return filter_value == actual


def matches(trigger_type: str, config: dict, event: dict) -> bool:
    """Un événement {type, ...champs} déclenche-t-il ce déclencheur ? Chaque clé de `config.filter` doit correspondre
    (jokers * ? acceptés pour les chaînes, listes = « l'un de »)."""
    if event.get("type") != trigger_type:
        return False
    return all(k in event and _match(v, event[k]) for k, v in (config.get("filter") or {}).items())
