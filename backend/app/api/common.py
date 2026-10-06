import uuid
from sqlalchemy import select
from app.core.errors import AppError


def ok(data, **extra):
    return {"success": True, "data": data, **extra}


def not_found(what: str) -> AppError:
    return AppError(404, "RESOURCE_NOT_FOUND", f"{what} introuvable")


async def owned(db, model, id_, org_id, what):
    q = select(model).where(model.id == id_, model.organization_id == org_id)
    if hasattr(model, "deleted_at"):
        q = q.where(model.deleted_at.is_(None))
    obj = (await db.execute(q)).scalar_one_or_none()
    if not obj:
        raise not_found(what)
    return obj
