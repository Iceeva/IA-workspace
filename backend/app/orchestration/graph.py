"""Graphe de tâches : dépendances, détection de cycles, couches parallélisables."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class GraphError(ValueError):
    pass


@dataclass
class TaskNode:
    id: str
    title: str
    agent: str
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    output: str = ""
    error: str | None = None
    tokens: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""  # modèle réellement utilisé (peut différer du modèle demandé après un fallback)


class TaskGraph:
    def __init__(self, nodes: list[TaskNode]):
        self.nodes: dict[str, TaskNode] = {}
        for n in nodes:
            if n.id in self.nodes:
                raise GraphError(f"Identifiant de tâche dupliqué: {n.id}")
            self.nodes[n.id] = n
        for n in nodes:
            for d in n.depends_on:
                if d not in self.nodes:
                    raise GraphError(f"La tâche '{n.id}' dépend de '{d}', qui n'existe pas")
        self.layers()  # lève GraphError en cas de cycle

    def layers(self) -> list[list[TaskNode]]:
        """Tri topologique par couches ; les tâches d'une couche sont indépendantes."""
        remaining = {i: set(n.depends_on) for i, n in self.nodes.items()}
        out: list[list[TaskNode]] = []
        while remaining:
            ready = [i for i, deps in remaining.items() if not deps]
            if not ready:
                raise GraphError("Cycle détecté dans les dépendances: " + ", ".join(sorted(remaining)))
            out.append([self.nodes[i] for i in ready])
            for i in ready:
                del remaining[i]
            for deps in remaining.values():
                deps.difference_update(ready)
        return out

    def upstream_outputs(self, node: TaskNode) -> str:
        return "\n\n".join(f"### {self.nodes[d].title} ({self.nodes[d].agent})\n{self.nodes[d].output}"
                           for d in node.depends_on)

    def add(self, node: TaskNode) -> None:
        """Ajout dynamique (replanification) ; refuse les doublons, les dépendances inconnues et les cycles."""
        if node.id in self.nodes:
            raise GraphError(f"Identifiant de tâche dupliqué: {node.id}")
        for d in node.depends_on:
            if d not in self.nodes:
                raise GraphError(f"La tâche '{node.id}' dépend de '{d}', qui n'existe pas")
        self.nodes[node.id] = node
        self.layers()
