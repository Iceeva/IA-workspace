import uuid
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.entities import AuditLog


async def audit(db: AsyncSession, action: str, *, user_id=None, org_id=None, resource="", resource_id="",
                request: Request | None = None, meta: dict | None = None) -> None:
    """Ajoute une ligne d'audit à la transaction en cours (validée avec l'action elle-même)."""
    db.add(AuditLog(action=action, user_id=user_id, organization_id=org_id, resource=resource,
                    resource_id=str(resource_id), ip=(request.client.host if request and request.client else ""),
                    meta=meta or {}))
