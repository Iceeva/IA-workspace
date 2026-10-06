"""Tool Registry + permissions + validation humaine (§20, §21, §22).

Principe : un agent ne reçoit JAMAIS tous les outils. Il reçoit des `grants` {outil: niveau} ; chaque action d'outil
exige un niveau minimum ; les actions dangereuses exigent en plus l'accord explicite d'un humain."""
from __future__ import annotations
import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from app.catalog.model import Permission

AuditSink = Callable[[str, dict], Awaitable[None]]


class ToolError(RuntimeError):
    """Erreur d'exécution d'un outil (message exploitable par l'agent)."""


class PermissionDenied(PermissionError):
    pass


class ApprovalDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Action:
    level: Permission
    handler: Callable[..., Awaitable[Any]]
    requires_approval: bool = False
    description: str = ""


@dataclass
class ToolDef:
    name: str
    description: str
    actions: dict[str, Action]
    status: str = "available"          # available | planned (déclaré mais sans implémentation)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "status": self.status,
                "actions": {n: {"level": a.level.name, "requires_approval": a.requires_approval,
                                "description": a.description} for n, a in self.actions.items()}}


class ToolRegistry:
    def __init__(self):
        self._t: dict[str, ToolDef] = {}

    def register(self, t: ToolDef) -> None:
        self._t[t.name] = t

    def get(self, name: str) -> ToolDef | None:
        return self._t.get(name)

    def all(self) -> list[ToolDef]:
        return sorted(self._t.values(), key=lambda t: t.name)

    def available(self) -> set[str]:
        return {t.name for t in self._t.values() if t.status == "available"}


@dataclass
class ApprovalRequest:
    tool: str
    action: str
    summary: str
    agent: str = ""


class Approver(Protocol):
    async def request(self, req: ApprovalRequest) -> bool: ...


class DenyAll:
    """Défaut sûr : sans interface de validation, toute action dangereuse est refusée."""
    async def request(self, req: ApprovalRequest) -> bool:
        return False


class CallbackApprover:
    def __init__(self, fn: Callable[[ApprovalRequest], Awaitable[bool]]):
        self.fn = fn

    async def request(self, req: ApprovalRequest) -> bool:
        return await self.fn(req)


class MemoryApprovalStore:
    """Validation humaine asynchrone : l'agent attend, l'interface appelle `decide`. Un délai sans réponse = refus."""

    def __init__(self, timeout_s: float = 300.0):
        self.timeout_s, self._ids = timeout_s, itertools.count(1)
        self.pending: dict[int, ApprovalRequest] = {}
        self._futs: dict[int, asyncio.Future] = {}

    async def request(self, req: ApprovalRequest) -> bool:
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid], self._futs[rid] = req, fut
        try:
            return await asyncio.wait_for(fut, self.timeout_s)
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending.pop(rid, None); self._futs.pop(rid, None)

    def decide(self, rid: int, approved: bool) -> bool:
        fut = self._futs.get(rid)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True


@dataclass
class ToolBox:
    """Boîte à outils d'UN agent : ses autorisations, son approbateur, sa trace d'audit."""
    registry: ToolRegistry
    grants: dict[str, Permission]
    approver: Approver = field(default_factory=DenyAll)
    audit: AuditSink | None = None
    agent: str = ""
    timeout_s: float = 30.0

    def visible_tools(self) -> list[str]:
        """Outils réellement présentés à l'agent (accordés ET disponibles)."""
        return sorted(n for n, p in self.grants.items() if p > Permission.NONE and (t := self.registry.get(n))
                      and t.status == "available")

    async def _log(self, kind: str, data: dict) -> None:
        if self.audit:
            await self.audit(kind, {"agent": self.agent, **data})

    async def call(self, tool: str, action: str, **args) -> Any:
        t = self.registry.get(tool)
        if t is None or t.status != "available":
            raise ToolError(f"Outil indisponible: {tool}")
        a = t.actions.get(action)
        if a is None:
            raise ToolError(f"Action inconnue: {tool}.{action}")
        granted = self.grants.get(tool, Permission.NONE)
        if granted < a.level:
            await self._log("tool.denied", {"tool": tool, "action": action, "needs": a.level.name,
                                            "granted": granted.name})
            raise PermissionDenied(f"{tool}.{action} exige {a.level.name} (accordé : {granted.name})")
        if a.requires_approval:
            summary = f"{tool}.{action}({', '.join(f'{k}={str(v)[:80]!r}' for k, v in args.items())})"
            if not await self.approver.request(ApprovalRequest(tool, action, summary, self.agent)):
                await self._log("tool.refused", {"tool": tool, "action": action})
                raise ApprovalDenied(f"Validation humaine refusée pour {tool}.{action}")
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(a.handler(**args), self.timeout_s)
        except (ToolError, PermissionError):
            raise
        except asyncio.TimeoutError as e:
            raise ToolError(f"{tool}.{action}: délai dépassé ({self.timeout_s}s)") from e
        except Exception as e:  # noqa: BLE001
            await self._log("tool.failed", {"tool": tool, "action": action, "error": str(e)[:200]})
            raise ToolError(f"{tool}.{action}: {e}") from e
        await self._log("tool.called", {"tool": tool, "action": action,
                                        "ms": int((time.monotonic() - t0) * 1000)})
        return res
