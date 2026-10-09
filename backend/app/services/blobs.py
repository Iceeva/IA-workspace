"""Stockage des fichiers utilisateur : adressable par contenu, dédupliqué, compressé puis chiffré (§28, §29).

Clés : « cas:<empreinte> » (nouveaux fichiers, empreinte HMAC propre à l'organisation : pas de fuite « ce fichier existe
déjà » entre organisations) ; toute autre clé est un objet hérité, lu et supprimé tel quel. Un objet CAS partagé n'est
supprimé que lorsque plus aucun fichier ne le référence."""
from __future__ import annotations
import uuid

from app.core.crypto import get_secretbox
from app.storage.backends import make_storage
from app.storage.cas import ContentStore

PREFIX = "cas:"


def _backend():
    from app.storage.backends import StorageConfigError
    try:
        return make_storage()
    except StorageConfigError as e:
        from app.core.errors import AppError   # import tardif : fastapi n'est requis que sur ce chemin d'erreur
        raise AppError(503, "STORAGE_NOT_CONFIGURED", str(e)) from e


def _cas(org_id: uuid.UUID) -> ContentStore:
    return ContentStore(_backend(), get_secretbox(), str(org_id))


async def store(org_id: uuid.UUID, data: bytes) -> str:
    return PREFIX + (await _cas(org_id).put(data)).hash


async def load(org_id: uuid.UUID, key: str) -> bytes:
    if key.startswith(PREFIX):
        return await _cas(org_id).get(key[len(PREFIX):])
    return await _backend().get(key)


def deletable(key: str, other_references: int) -> bool:
    """Un objet hérité est propre à son fichier ; un objet CAS n'est supprimé qu'une fois orphelin."""
    return not key.startswith(PREFIX) or other_references == 0


async def release(db, org_id: uuid.UUID, file_id: uuid.UUID, key: str) -> bool:
    """À appeler APRÈS avoir retiré/modifié la référence du fichier. Retourne True si l'objet physique a été supprimé."""
    from sqlalchemy import func, select
    from app.models.entities import StoredFile
    others = 0
    if key.startswith(PREFIX):
        others = (await db.execute(select(func.count()).select_from(StoredFile).where(
            StoredFile.storage_key == key, StoredFile.organization_id == org_id, StoredFile.id != file_id,
            StoredFile.deleted_at.is_(None)))).scalar_one()
    if not deletable(key, others):
        return False
    backend = _backend()
    await backend.delete(ContentStore.key_for(key[len(PREFIX):]) if key.startswith(PREFIX) else key)
    return True
