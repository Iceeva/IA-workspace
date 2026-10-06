"""Authentification (Bearer JWT ou X-API-Key) + contexte d'organisation. Toute requête métier passe par `ctx`."""
from dataclasses import dataclass
import uuid
import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import decode_claims, hash_api_key
from app.models.entities import RANK, ApiKey, OrganizationMember, Role, User
from app.services.redis_utils import is_revoked
from app.utils.logging import CTX

bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    user: User
    org_id: uuid.UUID
    role: Role

    def require(self, minimum: Role) -> None:
        if RANK[self.role] < RANK[minimum]:
            raise AppError(403, "FORBIDDEN", f"Rôle {minimum.value} minimum requis")


async def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                       x_api_key: str | None = Header(default=None),
                       db: AsyncSession = Depends(get_db)) -> User:
    user = None
    if cred:
        try:
            claims = decode_claims(cred.credentials, "access")
            if await is_revoked(claims["jti"]):
                raise AppError(401, "INVALID_TOKEN", "Session terminée")
            user = await db.get(User, uuid.UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError):
            raise AppError(401, "INVALID_TOKEN", "Jeton invalide ou expiré")
    elif x_api_key:
        key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(x_api_key),
                                                     ApiKey.deleted_at.is_(None)))).scalar_one_or_none()
        user = await db.get(User, key.user_id) if key else None
    else:
        raise AppError(401, "UNAUTHENTICATED", "Authentification requise")
    if not user or user.deleted_at:
        raise AppError(401, "INVALID_TOKEN", "Utilisateur introuvable")
    CTX["user_id"].set(str(user.id))
    return user


async def platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "Réservé aux administrateurs de la plateforme")
    return user


async def ctx(x_organization_id: str = Header(...), user: User = Depends(current_user),
              db: AsyncSession = Depends(get_db)) -> Ctx:
    """L'appartenance est vérifiée en base : l'en-tête seul ne donne aucun droit."""
    try:
        org = uuid.UUID(x_organization_id)
    except ValueError:
        raise AppError(400, "BAD_ORGANIZATION", "X-Organization-Id invalide")
    m = (await db.execute(select(OrganizationMember).where(
        OrganizationMember.organization_id == org, OrganizationMember.user_id == user.id,
        OrganizationMember.deleted_at.is_(None)))).scalar_one_or_none()
    if not m:
        raise AppError(404, "RESOURCE_NOT_FOUND", "Organisation introuvable")  # 404 : pas de fuite d'existence
    CTX["organization_id"].set(str(org))
    return Ctx(user, org, m.role)
