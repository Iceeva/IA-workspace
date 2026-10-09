"""Mode « pull » du Local Bridge : le serveur dépose des tâches de chat, le bridge (installé chez l'utilisateur) vient
les chercher en sortie (connexion initiée par la machine locale : aucun port à ouvrir, aucune URL locale côté serveur).

Isolation : chaque file est liée à un « scope » (organisation:utilisateur) ; seul son propriétaire peut réclamer ses
tâches et y répondre. Le bridge n'exécute que des appels de chat vers ses propres runtimes locaux."""
from __future__ import annotations
import asyncio
import json
import uuid
from typing import Protocol

OFFLINE_AFTER_S = 60


class BridgeTimeout(TimeoutError):
    pass


class JobBroker(Protocol):
    async def submit(self, scope: str, job: dict) -> str: ...
    async def claim(self, scope: str, wait_s: float) -> dict | None: ...
    async def complete(self, scope: str, job_id: str, result: dict) -> bool: ...
    async def wait_result(self, job_id: str, timeout_s: float) -> dict: ...
    async def heartbeat(self, scope: str, info: dict) -> None: ...
    async def status(self, scope: str) -> dict | None: ...


class MemoryBroker:
    """Courtier en mémoire (tests, mono-processus). En production multi-processus, utilisez RedisBroker."""

    def __init__(self, clock=None):
        import time
        self.clock = clock or time.monotonic
        self._q: dict[str, asyncio.Queue] = {}
        self._owner: dict[str, str] = {}
        self._res: dict[str, asyncio.Future] = {}
        self._hb: dict[str, tuple[float, dict]] = {}

    def _queue(self, scope: str) -> asyncio.Queue:
        return self._q.setdefault(scope, asyncio.Queue())

    async def submit(self, scope: str, job: dict) -> str:
        jid = uuid.uuid4().hex
        self._owner[jid] = scope
        self._res[jid] = asyncio.get_running_loop().create_future()
        await self._queue(scope).put({**job, "id": jid})
        return jid

    async def claim(self, scope: str, wait_s: float) -> dict | None:
        try:
            return await asyncio.wait_for(self._queue(scope).get(), wait_s)
        except asyncio.TimeoutError:
            return None

    async def complete(self, scope: str, job_id: str, result: dict) -> bool:
        fut = self._res.get(job_id)
        if self._owner.get(job_id) != scope or fut is None or fut.done():
            return False
        fut.set_result(result)
        return True

    async def wait_result(self, job_id: str, timeout_s: float) -> dict:
        try:
            return await asyncio.wait_for(asyncio.shield(self._res[job_id]), timeout_s)
        except asyncio.TimeoutError as e:
            raise BridgeTimeout("Le Local Bridge n'a pas répondu à temps") from e
        finally:
            if self._res[job_id].done():
                self._res.pop(job_id, None); self._owner.pop(job_id, None)

    async def heartbeat(self, scope: str, info: dict) -> None:
        self._hb[scope] = (self.clock(), info)

    async def status(self, scope: str) -> dict | None:
        hb = self._hb.get(scope)
        return hb[1] if hb and self.clock() - hb[0] <= OFFLINE_AFTER_S else None


class RedisBroker:
    """Même contrat sur Redis (plusieurs API/workers). Non couvert par les tests unitaires : voir docs/ROADMAP.md."""
    P = "aiw:bridge:"

    def __init__(self, redis):
        self.r = redis

    async def submit(self, scope: str, job: dict) -> str:
        jid = uuid.uuid4().hex
        await self.r.set(f"{self.P}owner:{jid}", scope, ex=900)
        await self.r.rpush(f"{self.P}jobs:{scope}", json.dumps({**job, "id": jid}))
        await self.r.expire(f"{self.P}jobs:{scope}", 900)
        return jid

    async def claim(self, scope: str, wait_s: float) -> dict | None:
        item = await self.r.blpop(f"{self.P}jobs:{scope}", timeout=max(1, int(wait_s)))
        return json.loads(item[1]) if item else None

    async def complete(self, scope: str, job_id: str, result: dict) -> bool:
        if await self.r.get(f"{self.P}owner:{job_id}") != scope:
            return False
        await self.r.rpush(f"{self.P}res:{job_id}", json.dumps(result))
        await self.r.expire(f"{self.P}res:{job_id}", 900)
        return True

    async def wait_result(self, job_id: str, timeout_s: float) -> dict:
        item = await self.r.blpop(f"{self.P}res:{job_id}", timeout=max(1, int(timeout_s)))
        if not item:
            raise BridgeTimeout("Le Local Bridge n'a pas répondu à temps")
        await self.r.delete(f"{self.P}owner:{job_id}")
        return json.loads(item[1])

    async def heartbeat(self, scope: str, info: dict) -> None:
        await self.r.set(f"{self.P}hb:{scope}", json.dumps(info), ex=OFFLINE_AFTER_S)

    async def status(self, scope: str) -> dict | None:
        raw = await self.r.get(f"{self.P}hb:{scope}")
        return json.loads(raw) if raw else None
