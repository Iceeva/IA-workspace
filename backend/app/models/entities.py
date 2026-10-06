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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
