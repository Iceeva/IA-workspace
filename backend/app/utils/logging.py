"""Logs JSON structurés avec contexte (user, org, workspace, exécution, agent) et masquage des secrets."""
import contextvars, json, logging, re
from datetime import datetime, timezone

CTX = {k: contextvars.ContextVar(k, default=None) for k in
       ("user_id", "organization_id", "workspace_id", "execution_id", "agent_id")}
_SECRET = re.compile(r"(eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}|sk-[A-Za-z0-9_-]{12,}|(?i:password|passwd|api[_-]?key|secret|token)\"?\s*[:=]\s*\"?[^\s\",}]+)")


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, r: logging.LogRecord) -> str:
        msg = redact(r.getMessage())
        if r.exc_info:
            msg += " | " + redact(self.formatException(r.exc_info))
        return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": r.levelname,
                           "service": self.service, **{k: v.get() for k, v in CTX.items()}, "message": msg},
                          ensure_ascii=False)


def setup_logging(service: str, level: int = logging.INFO) -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
