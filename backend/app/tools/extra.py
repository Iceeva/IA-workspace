"""Outils complémentaires (§20). Chaque outil est confiné et déclare le niveau minimal de chaque action ;
les actions à effet de bord exigent une validation humaine. Les dépendances externes sont injectables (tests)."""
from __future__ import annotations
import asyncio
import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin

from app.catalog.model import Permission
from app.storage.paths import UnsafePath, safe_path
from .registry import Action, ToolDef, ToolError

MAX_TEXT = 20_000


# ---- HTML → texte ----------------------------------------------------------------------------------------------------
class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links, self.skip, self.title, self._in_title = base, [], [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and len(self.links) < 30:
            href = dict(attrs).get("href")
            if href and not href.lower().startswith(("javascript:", "data:", "#")):
                self.links.append(urljoin(self.base, href))
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str, base: str = "") -> dict:
    p = _Text(base)
    p.feed(html[:2_000_000])
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return {"title": p.title, "text": text[:MAX_TEXT], "links": p.links}


# ---- terminal / javascript (sandbox Docker) ---------------------------------------------------------------------------
def _sandbox_tool(name: str, desc: str, language: str, arg: str) -> ToolDef:
    async def run(**kw) -> dict:
        from app.services.sandbox import SandboxUnavailable, run_code
        try:
            r = await run_code(language, kw[arg])
        except SandboxUnavailable as e:
            raise ToolError(str(e)) from e
        return {"exit_code": r.exit_code, "stdout": r.stdout, "stderr": r.stderr, "timed_out": r.timed_out}

    async def go(command: str = "", code: str = "") -> dict:
        return await run(**{arg: command if arg == "command" else code})
    return ToolDef(name, desc, {"run": Action(Permission.EXECUTE, go, requires_approval=True,
                                              description="Exécuter dans un conteneur jetable (validation humaine)")})


def terminal_tool() -> ToolDef:
    return _sandbox_tool("terminal", "Terminal ISOLÉ : commandes sh dans un conteneur jetable, sans réseau, "
                         "fichiers en lecture seule, CPU/RAM limités (jamais la machine hôte)", "shell", "command")


def javascript_tool() -> ToolDef:
    return _sandbox_tool("javascript", "JavaScript (Node) dans un conteneur jetable sans réseau", "node", "code")


# ---- HTTP, navigateur, recherche web ------------------------------------------------------------------------------------
def http_tool(http=None) -> ToolDef:
    async def _h(*a, **k):
        from app.workflows.http import safe_http
        return await (http or safe_http)(*a, **k)

    async def get(url: str, headers: dict | None = None) -> dict:
        code, text = await _h("GET", url, headers or {}, None)
        return {"status": code, "body": text[:MAX_TEXT]}

    async def request(method: str, url: str, body: str = "", headers: dict | None = None) -> dict:
        if method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
            raise ToolError("Méthode : POST, PUT, PATCH ou DELETE")
        code, text = await _h(method.upper(), url, headers or {}, body or None)
        return {"status": code, "body": text[:MAX_TEXT]}
    return ToolDef("http", "Appels HTTP(S) vers des adresses publiques (jamais le réseau interne)", {
        "get": Action(Permission.READ, get, description="GET"),
        "request": Action(Permission.WRITE, request, requires_approval=True, description="POST/PUT/PATCH/DELETE (validation humaine)")})


def browser_tool(http=None) -> ToolDef:
    async def open_(url: str) -> dict:
        from app.workflows.http import safe_http
        code, html = await (http or safe_http)("GET", url, {"User-Agent": "AIWorkspace-Browser/1.0"}, None)
        if code >= 400:
            raise ToolError(f"HTTP {code}")
        return {"status": code, **html_to_text(html, url)}
    return ToolDef("browser", "Lecture de pages web (texte et liens), sans exécuter de JavaScript", {
        "open": Action(Permission.READ, open_, description="Ouvrir une page et en extraire texte et liens")})


async def _default_json(url: str, headers: dict | None = None) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as c:
        r = await c.get(url, headers=headers or {})
    if r.status_code >= 400:
        raise ToolError(f"HTTP {r.status_code}")
    return r.json()


def web_search_tool(endpoint: str = "", fetch_json=None) -> ToolDef:
    """Instance SearXNG configurée par l'administrateur (JSON activé) ; l'agent ne fournit jamais l'URL."""
    async def search(query: str, limit: int = 5) -> list[dict]:
        if not endpoint:
            raise ToolError("Recherche web non configurée (SEARCH_URL)")
        data = await (fetch_json or _default_json)(f"{endpoint}?q={quote(query[:300])}&format=json")
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": (r.get("content") or "")[:300]}
                for r in data.get("results", [])[:max(1, min(int(limit), 10))]]
    return ToolDef("web_search", "Recherche web via une instance SearXNG configurée", {
        "search": Action(Permission.READ, search, description="Rechercher sur le web")})


# ---- GitHub (lecture seule) -------------------------------------------------------------------------------------------------
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


def github_tool(token: str = "", fetch_json=None) -> ToolDef:
    f = fetch_json or _default_json
    hdr = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}

    def repo_ok(repo: str) -> str:
        if not _REPO.match(repo):
            raise ToolError("Dépôt attendu sous la forme propriétaire/nom")
        return repo

    async def issues(repo: str, state: str = "open") -> list[dict]:
        if state not in ("open", "closed", "all"):
            raise ToolError("state : open, closed ou all")
        data = await f(f"https://api.github.com/repos/{repo_ok(repo)}/issues?state={state}&per_page=20", hdr)
        return [{"number": i["number"], "title": i["title"], "state": i["state"], "pull_request": "pull_request" in i,
                 "url": i["html_url"]} for i in data]

    async def file(repo: str, path: str, ref: str = "") -> str:
        try:
            clean = safe_path(path)
        except UnsafePath as e:
            raise ToolError(str(e)) from e
        if ref and not re.match(r"^[A-Za-z0-9_./-]{1,100}$", ref):
            raise ToolError("Référence invalide")
        data = await f(f"https://api.github.com/repos/{repo_ok(repo)}/contents/{quote(clean)}" + (f"?ref={ref}" if ref else ""), hdr)
        if isinstance(data, dict) and data.get("encoding") == "base64":
            import base64
            return base64.b64decode(data["content"]).decode("utf-8", "replace")[:MAX_TEXT]
        raise ToolError("Ce chemin n'est pas un fichier")
    return ToolDef("github", "GitHub en lecture seule : tickets/PR et contenu de fichiers", {
        "issues": Action(Permission.READ, issues, description="Lister tickets et pull requests"),
        "file": Action(Permission.READ, file, description="Lire un fichier d'un dépôt")})


# ---- base de données (SQLite du projet, lecture seule) ------------------------------------------------------------------
_SQL_START = re.compile(r"^\s*(select|with|pragma\s+table_info)\b", re.I)


def database_tool(root: str | Path) -> ToolDef:
    base = Path(root).resolve()

    def open_ro(db: str) -> sqlite3.Connection:
        try:
            p = (base / safe_path(db)).resolve()
        except UnsafePath as e:
            raise ToolError(str(e)) from e
        if base not in p.parents or not p.is_file():
            raise ToolError("Base introuvable dans l'espace de travail")
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        con.execute("PRAGMA query_only=ON")
        return con

    def _query(db: str, sql: str, limit: int) -> dict:
        if not _SQL_START.match(sql) or not sqlite3.complete_statement(sql if sql.rstrip().endswith(";") else sql + ";") \
                or sql.rstrip().rstrip(";").count(";"):
            raise ToolError("Une seule requête SELECT/WITH est autorisée")
        con = open_ro(db)
        try:
            cur = con.execute(sql)
            cols = [c[0] for c in cur.description or []]
            rows = cur.fetchmany(max(1, min(int(limit), 200)))
            return {"columns": cols, "rows": [list(r) for r in rows]}
        except sqlite3.Error as e:
            raise ToolError(f"SQL : {e}") from e
        finally:
            con.close()

    async def query(db: str, sql: str, limit: int = 100) -> dict:
        return await asyncio.to_thread(_query, db, sql, limit)

    async def tables(db: str) -> list[str]:
        r = await asyncio.to_thread(_query, db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", 200)
        return [x[0] for x in r["rows"]]
    return ToolDef("database", "Bases SQLite de l'espace de travail, en lecture seule", {
        "tables": Action(Permission.READ, tables, description="Lister les tables"),
        "query": Action(Permission.READ, query, description="Exécuter un SELECT (200 lignes max)")})


# ---- e-mail, PDF, images, déploiement, automatisation, RAG -------------------------------------------------------------------
def email_tool(sender=None) -> ToolDef:
    async def send(to: str, subject: str, body: str) -> str:
        if not re.match(r"^[^@\s]{1,64}@[^@\s]{1,255}$", to) or "\n" in subject or len(body) > 20_000:
            raise ToolError("Destinataire, objet ou corps invalide")
        fn, not_configured = sender, ()
        if fn is None:
            from app.services.mailer import MailNotConfigured, send_mail
            fn, not_configured = send_mail, (MailNotConfigured,)
        try:
            await fn(to, subject[:200], body)
        except not_configured as e:
            raise ToolError(str(e)) from e
        return f"e-mail envoyé à {to}"
    return ToolDef("email", "Envoi d'e-mails (SMTP configuré)", {
        "send": Action(Permission.WRITE, send, requires_approval=True, description="Envoyer un e-mail (validation humaine)")})


def pdf_tool(root: str | Path) -> ToolDef:
    base = Path(root).resolve()

    def _read(path: str, first: int, last: int) -> dict:
        from pypdf import PdfReader
        try:
            p = (base / safe_path(path)).resolve()
        except UnsafePath as e:
            raise ToolError(str(e)) from e
        if base not in p.parents or not p.is_file() or p.stat().st_size > 20_000_000:
            raise ToolError("PDF introuvable ou trop volumineux")
        r = PdfReader(str(p))
        n = len(r.pages)
        text = "\n".join((r.pages[i].extract_text() or "") for i in range(max(0, first - 1), min(n, last)))
        return {"pages": n, "text": text[:MAX_TEXT]}

    async def extract(path: str, first: int = 1, last: int = 10) -> dict:
        return await asyncio.to_thread(_read, path, int(first), int(last))
    return ToolDef("pdf", "Extraction de texte de PDF de l'espace de travail", {
        "extract": Action(Permission.READ, extract, description="Texte des pages first..last")})


def image_tool(root: str | Path) -> ToolDef:
    base = Path(root).resolve()

    def _path(rel: str) -> Path:
        try:
            p = (base / safe_path(rel)).resolve()
        except UnsafePath as e:
            raise ToolError(str(e)) from e
        if base not in p.parents:
            raise ToolError("Chemin hors de l'espace de travail")
        return p

    def _info(path: str) -> dict:
        from PIL import Image
        p = _path(path)
        if not p.is_file():
            raise ToolError("Image introuvable")
        with Image.open(p) as im:
            return {"format": im.format, "width": im.width, "height": im.height, "mode": im.mode}

    def _resize(path: str, out: str, width: int) -> str:
        from PIL import Image
        if not 16 <= int(width) <= 4096:
            raise ToolError("width entre 16 et 4096")
        src, dst = _path(path), _path(out)
        with Image.open(src) as im:
            h = max(1, round(im.height * int(width) / im.width))
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.resize((int(width), h)).save(dst)
        return f"{out} : {width}x{h}"

    async def info(path: str) -> dict: return await asyncio.to_thread(_info, path)
    async def resize(path: str, out: str, width: int) -> str: return await asyncio.to_thread(_resize, path, out, width)
    return ToolDef("image", "Informations et redimensionnement d'images de l'espace de travail", {
        "info": Action(Permission.READ, info, description="Format et dimensions"),
        "resize": Action(Permission.WRITE, resize, description="Redimensionner vers un nouveau fichier")})


def deploy_tool(hooks: dict[str, str], http=None) -> ToolDef:
    """Déclenche un hook de déploiement NOMMÉ par l'administrateur ; l'agent ne fournit jamais l'URL."""
    async def trigger(target: str) -> dict:
        url = hooks.get(target)
        if not url:
            raise ToolError(f"Cible inconnue. Cibles : {', '.join(sorted(hooks)) or 'aucune configurée'}")
        from app.workflows.http import safe_http
        code, text = await (http or safe_http)("POST", url, {}, None)
        if code >= 400:
            raise ToolError(f"Le hook a répondu HTTP {code}")
        return {"target": target, "status": code}
    return ToolDef("deploy", "Déclenchement de déploiements via des hooks nommés", {
        "trigger": Action(Permission.EXECUTE, trigger, requires_approval=True, description="Déployer (validation humaine)")})


def automation_tool(run_workflow) -> ToolDef:
    async def run(name: str, payload: dict | None = None) -> str:
        return await run_workflow(name, payload or {})
    return ToolDef("automation", "Lancer un workflow existant de l'organisation", {
        "run_workflow": Action(Permission.EXECUTE, run, requires_approval=True, description="Lancer un workflow (validation humaine)")})


def rag_tool(search) -> ToolDef:
    async def q(query: str, k: int = 5) -> list[dict]:
        return await search(query, max(1, min(int(k), 10)))
    return ToolDef("rag", "Recherche dans les documents indexés de l'organisation", {
        "search": Action(Permission.READ, q, description="Passages pertinents (recherche hybride)")})
