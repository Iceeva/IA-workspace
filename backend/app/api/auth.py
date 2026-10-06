import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import (create_access_token, create_action_token, create_refresh_token, decode_action_token,
                               decode_claims, hash_password, pw_fingerprint, verify_password)
from app.models.entities import Organization, OrganizationMember, Role, Subscription, User
from app.services.audit import audit
from app.services.mailer import MailNotConfigured, send_mail
from app.services.redis_utils import revoke
from .deps import bearer, current_user

router = APIRouter(prefix="/api", tags=["auth"])
log = logging.getLogger("auth")
PASSWORD = Field(min_length=10, max_length=128)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = PASSWORD
    full_name: str = Field(min_length=1, max_length=120)
    organization_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = PASSWORD


class VerifyIn(BaseModel):
    token: str


def _tokens(uid) -> dict:
    return {"success": True, "data": {"access_token": create_access_token(str(uid)),
                                      "refresh_token": create_refresh_token(str(uid))}}


async def _revoke_claims(claims: dict) -> None:
    ttl = int(claims["exp"] - datetime.now(timezone.utc).timestamp())
    await revoke(claims["jti"], ttl)


async def _send_verification(user: User) -> str:
    s = get_settings()
    tok = create_action_token(str(user.id), "verify_email", timedelta(days=2))
    try:
        await send_mail(user.email, "Confirmez votre adresse e-mail",
                        f"Bienvenue sur AI Workspace.\n\nConfirmez votre adresse: {s.frontend_url}/verify-email?token={tok}\n")
        return "sent"
    except MailNotConfigured:
        return "unavailable"
    except Exception:  # noqa: BLE001
        log.exception("échec d'envoi de l'e-mail de vérification")
        return "failed"


@router.post("/auth/register", status_code=201)
async def register(body: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none():
        raise AppError(409, "EMAIL_TAKEN", "Cette adresse e-mail est déjà utilisée")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), full_name=body.full_name)
    org = Organization(name=body.organization_name)
    db.add_all([user, org]); await db.flush()
    db.add_all([OrganizationMember(organization_id=org.id, user_id=user.id, role=Role.OWNER),
                Subscription(organization_id=org.id)])
    await audit(db, "auth.register", user_id=user.id, org_id=org.id, resource="user", resource_id=user.id, request=request)
    await db.commit()
    return {**_tokens(user.id), "organization_id": str(org.id), "email_verification": await _send_verification(user)}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not user or user.deleted_at or not verify_password(body.password, user.password_hash):
        await audit(db, "auth.login_failed", request=request)
        await db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "E-mail ou mot de passe incorrect")
    await audit(db, "auth.login", user_id=user.id, request=request); await db.commit()
    return _tokens(user.id)


@router.post("/auth/refresh")
async def refresh(body: RefreshIn):
    from app.services.redis_utils import is_revoked
    try:
        claims = decode_claims(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise AppError(401, "INVALID_TOKEN", "Jeton de rafraîchissement invalide")
    if await is_revoked(claims["jti"]):
        raise AppError(401, "INVALID_TOKEN", "Jeton de rafraîchissement révoqué")
    await _revoke_claims(claims)  # rotation : un refresh token ne sert qu'une fois
    return _tokens(claims["sub"])


@router.post("/auth/logout", status_code=204)
async def logout(body: RefreshIn, user: User = Depends(current_user),
                 cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    for token, kind in ((body.refresh_token, "refresh"), (cred.credentials if cred else "", "access")):
        try:
            await _revoke_claims(decode_claims(token, kind))
        except jwt.PyJWTError:
            pass


@router.post("/auth/forgot-password")
async def forgot_password(body: EmailIn, db: AsyncSession = Depends(get_db)):
    """Réponse identique que le compte existe ou non (pas d'énumération)."""
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user and not user.deleted_at:
        tok = create_action_token(str(user.id), "reset_password", timedelta(hours=1), pw_fingerprint(user.password_hash))
        try:
            await send_mail(user.email, "Réinitialisation du mot de passe",
                            f"Réinitialisez votre mot de passe (valable 1 h): {get_settings().frontend_url}/reset-password?token={tok}\n")
        except MailNotConfigured:
            log.warning("SMTP non configuré : e-mail de réinitialisation non envoyé")
        except Exception:  # noqa: BLE001
            log.exception("échec d'envoi de l'e-mail de réinitialisation")
    return {"success": True, "data": {"message": "Si ce compte existe, un e-mail vient d'être envoyé."}}


@router.post("/auth/reset-password")
async def reset_password(body: ResetIn, request: Request, db: AsyncSession = Depends(get_db)):
    bad = AppError(400, "INVALID_TOKEN", "Lien invalide ou expiré")
    try:
        claims = decode_action_token(body.token, "reset_password")
    except jwt.PyJWTError:
        raise bad
    user = await db.get(User, claims["sub"])
    if not user or claims.get("fp") != pw_fingerprint(user.password_hash):
        raise bad  # déjà utilisé ou mot de passe déjà changé
    user.password_hash = hash_password(body.password)
    await audit(db, "auth.password_reset", user_id=user.id, request=request); await db.commit()
    return {"success": True, "data": {"message": "Mot de passe mis à jour"}}


@router.post("/auth/verify-email")
async def verify_email(body: VerifyIn, db: AsyncSession = Depends(get_db)):
    try:
        claims = decode_action_token(body.token, "verify_email")
    except jwt.PyJWTError:
        raise AppError(400, "INVALID_TOKEN", "Lien invalide ou expiré")
    user = await db.get(User, claims["sub"])
    if not user:
        raise AppError(400, "INVALID_TOKEN", "Lien invalide ou expiré")
    user.email_verified = True; await db.commit()
    return {"success": True, "data": {"email_verified": True}}


@router.post("/auth/resend-verification")
async def resend_verification(user: User = Depends(current_user)):
    if user.email_verified:
        return {"success": True, "data": {"status": "already_verified"}}
    return {"success": True, "data": {"status": await _send_verification(user)}}


@router.get("/me")
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(OrganizationMember, Organization).join(Organization)
            .where(OrganizationMember.user_id == user.id))).all()
    return {"success": True, "data": {"id": str(user.id), "email": user.email, "full_name": user.full_name,
            "email_verified": user.email_verified, "is_platform_admin": user.is_platform_admin,
            "organizations": [{"id": str(o.id), "name": o.name, "role": m.role.value} for m, o in rows]}}
