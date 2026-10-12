"""Registre des runtimes persistant (§19). Idempotent : une base neuve a déjà la table via 0001."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models.entities import Base
    bind = op.get_bind()
    if "runtime_records" not in sa.inspect(bind).get_table_names():
        Base.metadata.tables["runtime_records"].create(bind=bind)


def downgrade() -> None:
    op.drop_table("runtime_records")
