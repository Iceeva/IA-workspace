"""Fournisseurs configurables, préférences de routage/budget, coût et tokens détaillés dans l'usage.

Idempotent : sur une base neuve, 0001 a déjà créé ces objets à partir des modèles courants."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_USAGE_COLS = {"tokens_in": sa.Integer(), "tokens_out": sa.Integer(), "cost_usd": sa.Float()}


def upgrade() -> None:
    from app.models.entities import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)          # crée provider_configs et ai_settings s'ils manquent
    have = {c["name"] for c in sa.inspect(bind).get_columns("usage_records")}
    for name, typ in _USAGE_COLS.items():
        if name not in have:
            op.add_column("usage_records", sa.Column(name, typ, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_table("ai_settings")
    op.drop_table("provider_configs")
    for name in _USAGE_COLS:
        op.drop_column("usage_records", name)
