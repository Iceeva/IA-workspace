"""Chat : mode agent seul (flux SSE) ; modes équipe/workflow → création d'une exécution suivie par le client."""
import json
import uuid
from typing import Literal
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.core.config import get_settings
from app.core.db import get_db, session_maker
from app.core.errors import AppError
from app.llm.base import LLMConfigError, LLMError, LLMResponse, Message
from app.llm.providers import get_provider
from app.memory.store import DBMemoryStore
from app.models.entities import Agent, Execution, Project, Role, UsageRecord
from app.services.admin_config import ensure_provider_enabled
from app.services.queue import enqueue
from app.services.quota import ensure_token_budget
from .common import ok, owned
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["chat"])


class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class ChatIn(BaseModel):
    mode: Literal["single", "team"] = "single"
    messages: list[ChatMsg] = Field(min_length=1, max_length=60)
    agent_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    conversation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=80)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(b: ChatIn, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    if b.messages[-1].role != "user":
        raise AppError(422, "VALIDATION_ERROR", "Le dernier message doit venir de l'utilisateur")
    await ensure_token_budget(db, c.org_id)
    await ensure_provider_enabled(db)
    question = b.messages[-1].content

    if b.mode == "team":  # orchestration longue : jamais dans la requête HTTP
        if not b.project_id:
            raise AppError(422, "VALIDATION_ERROR", "project_id est requis en mode équipe")
        await owned(db, Project, b.project_id, c.org_id, "Projet")
        e = Execution(organization_id=c.org_id, project_id=b.project_id, created_by=c.user.id, mission=question)
        db.add(e); await db.commit(); await enqueue(str(e.id))
        return ok({"mode": "team", "execution_id": str(e.id)})

    agent = await owned(db, Agent, b.agent_id, c.org_id, "Agent") if b.agent_id else None
    mem = DBMemoryStore(db, c.org_id)
    ctx_parts = [m.content for m in await mem.recall("project", str(b.project_id), question, 4)] if b.project_id else []
    ctx_parts += [f"[{ch.file_id}#{ch.idx}] {ch.content}" for ch in await mem.search_files(question, 4)]
    system = (agent.system_prompt if agent else "Tu es un assistant technique précis et concis.") + \
        "\n\n" + BaseAgent.GUARD + ("\n\n<context>\n" + "\n---\n".join(ctx_parts) + "\n</context>" if ctx_parts else "")
    model = agent.model if agent else get_settings().default_model
    temp = agent.temperature if agent else 0.3
    try:
        provider = get_provider()
    except LLMConfigError as e:
        raise AppError(503, "LLM_NOT_CONFIGURED", str(e))
    msgs = [Message("system", system), *[Message(m.role, m.content) for m in b.messages]]
    org_id, user_id, conv = c.org_id, c.user.id, b.conversation_id

    async def gen():
        final, text = None, []
        try:
            async for item in provider.stream(msgs, model=model, temperature=temp):
                if isinstance(item, LLMResponse):
                    final = item
                else:
                    text.append(item); yield _sse({"delta": item})
        except (LLMConfigError, LLMError) as e:
            yield _sse({"error": str(e)}); return
        answer, tokens = "".join(text), final.total_tokens if final else 0
        async with session_maker()() as s:  # session propre : celle de la requête peut être fermée
            m = DBMemoryStore(s, org_id)
            await m.add("conversation", conv, f"Q: {question}\nR: {answer}"[:20000], {"by": str(user_id)})
            s.add(UsageRecord(organization_id=org_id, agent=agent.role if agent else "", model=model, tokens=tokens))
            await s.commit()
        yield _sse({"done": True, "tokens": tokens, "conversation_id": conv})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
