"""Schéma initial.

Amorçage : crée toutes les tables à partir des modèles tels qu'ils étaient à cette version.
Les évolutions suivantes doivent être de vraies migrations (`alembic revision --autogenerate`).
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models.entities import Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.models.entities import Base
    Base.metadata.drop_all(bind=op.get_bind())
