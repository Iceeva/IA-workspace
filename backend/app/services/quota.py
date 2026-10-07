import uuid
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.models.entities import AiSettings, StoredFile, Subscription, UsageRecord
from app.services.budget import BudgetPolicy, evaluate


def month_start() -> datetime:
    n = datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def subscription(db: AsyncSession, org_id: uuid.UUID) -> Subscription:
    sub = (await db.execute(select(Subscription).where(Subscription.organization_id == org_id))).scalar_one_or_none()
    if not sub:
        sub = Subscription(organization_id=org_id)
        db.add(sub); await db.flush()
    return sub


async def tokens_this_month(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (await db.execute(select(func.coalesce(func.sum(UsageRecord.tokens), 0)).where(
        UsageRecord.organization_id == org_id, UsageRecord.created_at >= month_start()))).scalar_one()


async def storage_bytes(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (await db.execute(select(func.coalesce(func.sum(StoredFile.size), 0)).where(
        StoredFile.organization_id == org_id, StoredFile.deleted_at.is_(None)))).scalar_one()


async def ensure_token_budget(db: AsyncSession, org_id: uuid.UUID) -> None:
    sub = await subscription(db, org_id)
    if await tokens_this_month(db, org_id) >= sub.monthly_token_limit:
        raise AppError(402, "QUOTA_EXCEEDED", "Quota mensuel de tokens atteint pour cette organisation")


async def ensure_storage_budget(db: AsyncSession, org_id: uuid.UUID, incoming: int) -> None:
    sub = await subscription(db, org_id)
    if await storage_bytes(db, org_id) + incoming > sub.storage_limit_mb * 1024 * 1024:
        raise AppError(402, "STORAGE_QUOTA_EXCEEDED", "Quota de stockage atteint pour cette organisation")


async def ensure_cost_budget(db: AsyncSession, org_id: uuid.UUID, confirmed: bool = False) -> None:
    """Budget mensuel en dollars (§39) : bloque, ou exige une confirmation explicite selon `on_limit`."""
    s = (await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))).scalar_one_or_none()
    if s is None or s.monthly_budget_usd is None:
        return
    spent = (await db.execute(select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
        UsageRecord.organization_id == org_id, UsageRecord.created_at >= month_start()))).scalar_one()
    d = evaluate(BudgetPolicy(s.monthly_budget_usd, s.on_limit), float(spent), 0.0, confirmed)
    if not d.allowed:
        raise AppError(402, "BUDGET_CONFIRMATION_REQUIRED" if d.needs_confirmation else "BUDGET_EXCEEDED", d.reason)
