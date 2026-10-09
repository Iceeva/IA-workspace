"""Outils intégrés. Tous sont confinés ; les actions à effet de bord exigent une validation humaine."""
from __future__ import annotations
import ast
import asyncio
import operator as op
import shutil
from pathlib import Path

from app.catalog.model import Permission
from app.storage.paths import UnsafePath, safe_path
from .registry import Action, ToolDef, ToolError, ToolRegistry

MAX_READ = 1_000_000
_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos}


def safe_eval(expr: str) -> float:
    """Arithmétique pure : pas de noms, pas d'appels, exposant borné."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(r) > 64:
                raise ToolError("Exposant trop grand")
            return _OPS[type(n.op)](l, r)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ToolError("Expression non autorisée")
    if len(expr) > 200:
        raise ToolError("Expression trop longue")
    try:
        return ev(ast.parse(expr, mode="eval"))
    except (SyntaxError, ZeroDivisionError) as e:
        raise ToolError(f"Expression invalide: {e}") from e


def filesystem_tool(root: str | Path) -> ToolDef:
    base = Path(root).resolve()

    def resolve(rel: str) -> Path:
        try:
            p = (base / safe_path(rel)).resolve()
        except UnsafePath as e:
            raise ToolError(str(e)) from e
        if base != p and base not in p.parents:  # liens symboliques compris
            raise ToolError("Chemin hors de l'espace de travail")
        return p

    async def read(path: str) -> str:
        p = resolve(path)
        if not p.is_file():
            raise ToolError("Fichier introuvable")
        if p.stat().st_size > MAX_READ:
            raise ToolError("Fichier trop volumineux")
        return p.read_text(encoding="utf-8", errors="replace")

    async def ls(path: str = ".") -> list[str]:
        p = base if path in (".", "") else resolve(path)
        if not p.is_dir():
            raise ToolError("Dossier introuvable")
        return sorted(f"{c.name}{'/' if c.is_dir() else ''}" for c in p.iterdir())[:500]

    async def write(path: str, content: str) -> str:
        if len(content.encode()) > MAX_READ:
            raise ToolError("Contenu trop volumineux")
        p = resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"{len(content)} caractères écrits dans {path}"

    async def delete(path: str) -> str:
        p = resolve(path)
        if p == base:
            raise ToolError("Impossible de supprimer la racine")
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)
        return f"{path} supprimé"

    return ToolDef("filesystem", "Lecture/écriture de fichiers dans l'espace de travail du projet", {
        "read": Action(Permission.READ, read, description="Lire un fichier texte"),
        "list": Action(Permission.READ, ls, description="Lister un dossier"),
        "write": Action(Permission.WRITE, write, description="Écrire un fichier"),
        "delete": Action(Permission.WRITE, delete, requires_approval=True, description="Supprimer (validation humaine)")})


def calculator_tool() -> ToolDef:
    async def calc(expression: str) -> float:
        return safe_eval(expression)
    return ToolDef("calculator", "Calculatrice arithmétique sûre", {"eval": Action(Permission.READ, calc)})


def git_tool(root: str | Path) -> ToolDef:
    base = str(Path(root).resolve())

    async def run(*args: str) -> str:
        if shutil.which("git") is None:
            raise ToolError("git n'est pas installé")
        p = await asyncio.create_subprocess_exec("git", "-C", base, *args, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        if p.returncode:
            raise ToolError(err.decode("utf-8", "replace")[:300])
        return out.decode("utf-8", "replace")[:20_000]

    async def status() -> str: return await run("status", "--short", "--branch")
    async def log(n: int = 10) -> str: return await run("log", "--oneline", f"-{max(1, min(int(n), 50))}")
    async def diff() -> str: return await run("diff", "--stat")
    return ToolDef("git", "Git en lecture seule (statut, historique, diff)", {
        "status": Action(Permission.READ, status), "log": Action(Permission.READ, log),
        "diff": Action(Permission.READ, diff)})


def python_tool() -> ToolDef:
    async def run_py(code: str) -> dict:
        from app.services.sandbox import SandboxUnavailable, run_code  # Docker requis : jamais dans l'API ni le worker
        try:
            r = await run_code("python", code)
        except SandboxUnavailable as e:
            raise ToolError(str(e)) from e
        return {"exit_code": r.exit_code, "stdout": r.stdout, "stderr": r.stderr, "timed_out": r.timed_out}
    return ToolDef("python", "Exécution de Python dans une sandbox Docker (sans réseau, CPU/RAM limités)", {
        "run": Action(Permission.EXECUTE, run_py, requires_approval=True,
                      description="Exécuter du code (validation humaine)")})


def default_registry(workspace_root: str | Path = ".", *, search_url: str = "", github_token: str = "",
                     deploy_hooks: dict[str, str] | None = None, run_workflow=None, rag_search=None) -> ToolRegistry:
    """Registre complet. Les outils qui exigent une configuration (recherche web, déploiement, RAG, automatisation)
    existent toujours mais répondent par une erreur explicite tant qu'ils ne sont pas configurés."""
    from . import extra
    reg = ToolRegistry()
    for t in (filesystem_tool(workspace_root), calculator_tool(), git_tool(workspace_root), python_tool(),
              extra.terminal_tool(), extra.javascript_tool(), extra.http_tool(), extra.browser_tool(),
              extra.web_search_tool(search_url), extra.github_tool(github_token), extra.database_tool(workspace_root),
              extra.email_tool(), extra.pdf_tool(workspace_root), extra.image_tool(workspace_root),
              extra.deploy_tool(deploy_hooks or {})):
        reg.register(t)
    if run_workflow:
        reg.register(extra.automation_tool(run_workflow))
    if rag_search:
        reg.register(extra.rag_tool(rag_search))
    return reg
