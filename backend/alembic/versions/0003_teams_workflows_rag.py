"""Équipes, agents personnalisés, workflows/déclencheurs/exécutions, approbations, RAG (embeddings), options de fournisseurs.

Idempotent : sur une base neuve, 0001 a déjà créé ces objets à partir des modèles courants."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_COLUMNS = {
    "provider_configs": [("options", sa.JSON())],
    "ai_settings": [("embedding_provider", sa.String(60)), ("embedding_model", sa.String(160))],
    "file_chunks": [("embedding", sa.JSON()), ("embed_model", sa.String(80))],
    "executions": [("team_id", sa.Uuid())],
}
_TABLES = ("teams", "custom_agents", "workflows", "workflow_triggers", "workflow_runs", "approval_requests")


def upgrade() -> None:
    from app.models.entities import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)           # crée les nouvelles tables si elles manquent
    insp = sa.inspect(bind)
    for table, cols in _COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for name, typ in cols:
            if name not in have:
                op.add_column(table, sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    for t in reversed(_TABLES):
        op.drop_table(t)
    for table, cols in _COLUMNS.items():
        for name, _ in cols:
            op.drop_column(table, name)
