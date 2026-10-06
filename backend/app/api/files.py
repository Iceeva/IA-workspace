import uuid
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models.entities import FileChunk, Role, StoredFile
from app.services.audit import audit
from app.services.codefs import make_diff
from app.services.projectfiles import write_file
from app.storage.backends import StorageConfigError, make_storage
from app.storage.paths import UnsafePath, safe_path
from app.storage.validation import InvalidUpload
from .common import ok, owned
from .deps import Ctx, ctx

router = APIRouter(prefix="/api", tags=["files"])


def _storage():
    try:
        return make_storage()
    except StorageConfigError as e:
        raise AppError(503, "STORAGE_NOT_CONFIGURED", str(e))


def _dto(f: StoredFile) -> dict:
    return {"id": str(f.id), "path": f.path, "size": f.size, "content_type": f.content_type, "indexed": f.indexed,
            "project_id": str(f.project_id) if f.project_id else None, "created_at": f.created_at.isoformat()}


@router.post("/files", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), project_id: uuid.UUID | None = Form(None),
                 path: str | None = Form(None), c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # on ne lit jamais plus que la limite
    try:
        vpath = safe_path(path or file.filename or "")
        f, _ = await write_file(db, c.org_id, c.user.id, project_id, vpath, data)
    except UnsafePath as e:
        raise AppError(422, "UNSAFE_PATH", str(e))
    except InvalidUpload as e:
        raise AppError(422, e.code, e.message)
    await audit(db, "file.upload", user_id=c.user.id, org_id=c.org_id, resource="file", resource_id=f.id, request=request)
    await db.commit()
    return ok(_dto(f))


@router.get("/files")
async def list_files(project_id: uuid.UUID | None = None, limit: int = Query(200, le=500), offset: int = Query(0, ge=0),
                     c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    q = select(StoredFile).where(StoredFile.organization_id == c.org_id, StoredFile.deleted_at.is_(None))
    if project_id:
        q = q.where(StoredFile.project_id == project_id)
    rows = (await db.execute(q.order_by(StoredFile.path).limit(limit).offset(offset))).scalars()
    return ok([_dto(f) for f in rows])


@router.get("/files/{file_id}/download")
async def download(file_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    f = await owned(db, StoredFile, file_id, c.org_id, "Fichier")
    name = f.path.rsplit("/", 1)[-1].replace('"', "")
    return Response(await _storage().get(f.storage_key), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/files/{file_id}/content")
async def read_content(file_id: uuid.UUID, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    f = await owned(db, StoredFile, file_id, c.org_id, "Fichier")
    raw = await _storage().get(f.storage_key)
    try:
        return ok({"path": f.path, "content": raw.decode("utf-8")})
    except UnicodeDecodeError:
        raise AppError(415, "NOT_TEXT", "Ce fichier n'est pas un fichier texte")


class ContentIn(BaseModel):
    content: str


@router.put("/files/{file_id}/content")
async def write_content(file_id: uuid.UUID, b: ContentIn, request: Request, c: Ctx = Depends(ctx),
                        db: AsyncSession = Depends(get_db)):
    """Sauvegarde depuis l'éditeur Monaco ; renvoie le diff unifié de la modification."""
    c.require(Role.MEMBER)
    f = await owned(db, StoredFile, file_id, c.org_id, "Fichier")
    old = (await _storage().get(f.storage_key)).decode("utf-8", "replace")
    try:
        await write_file(db, c.org_id, c.user.id, f.project_id, f.path, b.content.encode())
    except InvalidUpload as e:
        raise AppError(422, e.code, e.message)
    await audit(db, "file.edit", user_id=c.user.id, org_id=c.org_id, resource="file", resource_id=f.id, request=request)
    await db.commit()
    return ok({"diff": make_diff(old, b.content, f.path)})


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, request: Request, c: Ctx = Depends(ctx), db: AsyncSession = Depends(get_db)):
    c.require(Role.MEMBER)
    f = await owned(db, StoredFile, file_id, c.org_id, "Fichier")
    f.deleted_at = func.now()
    await db.execute(delete(FileChunk).where(FileChunk.file_id == f.id))
    await audit(db, "file.delete", user_id=c.user.id, org_id=c.org_id, resource="file", resource_id=f.id, request=request)
    await db.commit()
    await _storage().delete(f.storage_key)
