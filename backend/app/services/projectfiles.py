"""Écriture d'un fichier (validation, quota, stockage objet, indexation). Partagé par l'API et le worker."""
import asyncio, hashlib, mimetypes, uuid
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import FileChunk, Project, StoredFile
from app.services.quota import ensure_storage_budget
from app.storage.backends import make_storage
from app.storage.extract import chunk_text, extract_text
from app.storage.validation import validate_upload


async def _index(db: AsyncSession, f: StoredFile, ext: str, data: bytes) -> None:
    await db.execute(delete(FileChunk).where(FileChunk.file_id == f.id))
    try:
        text = await asyncio.to_thread(extract_text, ext, data)
    except Exception:  # noqa: BLE001 — fichier valide mais illisible : stocké, non indexé
        f.indexed = False
        return
    for i, c in enumerate(chunk_text(text)):
        db.add(FileChunk(organization_id=f.organization_id, file_id=f.id, idx=i, content=c))
    f.indexed = bool(text.strip())


async def write_file(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, project_id: uuid.UUID | None,
                     path: str, data: bytes) -> tuple[StoredFile, str]:
    """`path` doit déjà être passé par safe_path. Retourne (fichier, ancien contenu texte)."""
    checked = validate_upload(path, data, get_settings().max_upload_mb * 1024 * 1024)
    if project_id and not (await db.execute(select(Project.id).where(
            Project.id == project_id, Project.organization_id == org_id, Project.deleted_at.is_(None)))).first():
        from app.core.errors import AppError
        raise AppError(404, "RESOURCE_NOT_FOUND", "Projet introuvable")
    storage = make_storage()
    existing = (await db.execute(select(StoredFile).where(
        StoredFile.organization_id == org_id, StoredFile.project_id == project_id, StoredFile.path == path,
        StoredFile.deleted_at.is_(None)))).scalar_one_or_none()
    await ensure_storage_budget(db, org_id, max(0, len(data) - (existing.size if existing else 0)))
    old = ""
    if existing and checked.is_text:
        old = (await storage.get(existing.storage_key)).decode("utf-8", "replace")
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    f = existing or StoredFile(organization_id=org_id, project_id=project_id, path=path, created_by=user_id,
                               storage_key=f"{org_id}/{uuid.uuid4().hex}", content_type=ctype, size=0, sha256="")
    await storage.put(f.storage_key, data, ctype)
    f.size, f.sha256, f.content_type = len(data), hashlib.sha256(data).hexdigest(), ctype
    if not existing:
        db.add(f)
    await db.flush()
    await _index(db, f, checked.ext, data)
    return f, old
