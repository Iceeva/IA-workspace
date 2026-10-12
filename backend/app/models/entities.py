"""Modèles SQLAlchemy 2. Chaque ressource métier porte organization_id (isolation de tenant)."""
from __future__ import annotations
import enum, uuid
from datetime import datetime
from sqlalchemy import JSON, Boolean, Uuid, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    OWNER = "OWNER"; ADMIN = "ADMIN"; MEMBER = "MEMBER"; VIEWER = "VIEWER"


RANK = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Mixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Mixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    is_platform_admin: Mapped[bool] = mapped_column(default=False)
    email_verified: Mapped[bool] = mapped_column(default=False)


class Organization(Mixin, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(120))


class OrganizationMember(Mixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.MEMBER)


class Workspace(Mixin, Base):
    __tablename__ = "workspaces"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class Project(Mixin, Base):
    __tablename__ = "projects"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")


class Agent(Mixin, Base):
    __tablename__ = "agents"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120))
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="idle")


class Execution(Mixin, Base):
    __tablename__ = "executions"
    __table_args__ = (Index("ix_exec_org_created", "organization_id", "created_at"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    mission: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    workflow: Mapped[list | None] = mapped_column(JSON, nullable=True)  # graphe personnalisé (sinon: Planner)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # équipe : restreint le pool d'agents
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events: Mapped[list["ExecutionEvent"]] = relationship(back_populates="execution", order_by="ExecutionEvent.seq")


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    execution: Mapped[Execution] = relationship(back_populates="events")


# ---------------------------------------------------------------- tâches et messages
class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("execution_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    sender: Mapped[str] = mapped_column(String(60))
    recipient: Mapped[str] = mapped_column(String(60))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- mémoire et fichiers
class Memory(Mixin, Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_mem_scope", "organization_id", "scope", "scope_id"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    scope: Mapped[str] = mapped_column(String(20))      # conversation | project | agent
    scope_id: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # prévu pour un futur Embedder


class StoredFile(Mixin, Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("organization_id", "project_id", "path"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(500))      # chemin virtuel normalisé
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class FileChunk(Base):
    __tablename__ = "file_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(80), nullable=True)


# ---------------------------------------------------------------- plateforme
class LLMProviderConfig(Base):
    __tablename__ = "llm_providers"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LLMModelConfig(Base):
    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider", "model_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(ForeignKey("llm_providers.name"))
    model_id: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_org_time", "organization_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("executions.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderConfig(Mixin, Base):
    """Fournisseur d'IA configuré par une organisation. La clé API n'est stockée que chiffrée."""
    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_provider_org_name"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    models: Mapped[list] = mapped_column(JSON, default=list)   # [{id, caps, quality, speed, cost_in, cost_out, context}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    local: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict)   # api_version (Azure), region (Bedrock), …


class AiSettings(Mixin, Base):
    """Préférences de routage des modèles, confidentialité et budget d'une organisation (une ligne par organisation)."""
    __tablename__ = "ai_settings"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), unique=True)
    mode: Mapped[str] = mapped_column(String(12), default="auto")        # single | per_agent | auto
    single_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    per_agent: Mapped[dict] = mapped_column(JSON, default=dict)
    weights: Mapped[dict] = mapped_column(JSON, default=lambda: {"quality": 0.5, "speed": 0.2, "cost": 0.3})
    local_only: Mapped[bool] = mapped_column(Boolean, default=False)
    sensitive_local: Mapped[bool] = mapped_column(Boolean, default=False)
    prefer_local: Mapped[bool] = mapped_column(Boolean, default=False)
    max_blended_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback: Mapped[list] = mapped_column(JSON, default=list)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_limit: Mapped[str] = mapped_column(String(10), default="block")    # block | confirm
    embedding_provider: Mapped[str | None] = mapped_column(String(60), nullable=True)  # nom d'un ProviderConfig
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)   # vide = embeddings lexicaux locaux


class Subscription(Mixin, Base):
    __tablename__ = "subscriptions"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), unique=True)
    plan: Mapped[str] = mapped_column(String(30), default="free")
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=500_000)
    storage_limit_mb: Mapped[int] = mapped_column(Integer, default=500)


class ApiKey(Mixin, Base):
    __tablename__ = "api_keys"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 ; la clé n'est jamais stockée en clair


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(60), default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- équipes, agents personnalisés, automatisation
class Team(Mixin, Base):
    """Équipe d'agents (§37) : un sous-ensemble du catalogue que l'orchestrateur dirige pour une mission."""
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_team_org_name"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    agent_ids: Mapped[list] = mapped_column(JSON, default=list)   # identifiants du catalogue ou d'agents personnalisés


class CustomAgent(Mixin, Base):
    """Agent créé par l'utilisateur (§36). Fusionné au catalogue de son organisation uniquement."""
    __tablename__ = "custom_agents"
    __table_args__ = (UniqueConstraint("organization_id", "agent_id", name="uq_custom_agent"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(40))
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Workflow(Mixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_workflow_org_name"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # projet dont les fichiers sont accessibles


class WorkflowTrigger(Mixin, Base):
    __tablename__ = "workflow_triggers"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))      # schedule | webhook | github | file_added | api_event | agent_event | db_event
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRun(Mixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_wfrun_status", "status", "created_at"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")   # PENDING RUNNING COMPLETED FAILED CANCELLED
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    node_states: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequest(Mixin, Base):
    """Validation humaine (§22) : une action sensible attend la décision d'un membre de l'organisation."""
    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approval_status", "organization_id", "status"),)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    agent: Mapped[str] = mapped_column(String(60), default="")
    tool: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="PENDING")   # PENDING APPROVED DENIED EXPIRED
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeRecord(Base):
    """Registre des runtimes (§19) persistant côté serveur : ce que le Local Bridge d'un utilisateur a déclaré, avec sa dernière vue."""
    __tablename__ = "runtime_records"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "runtime_id", name="uq_runtime_org_user_rid"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    runtime_id: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    models: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
