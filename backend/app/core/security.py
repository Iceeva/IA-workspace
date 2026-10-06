"""Hachage scrypt (stdlib) et JWT access/refresh à secrets distincts."""
import base64, hashlib, hmac, os, uuid
from datetime import datetime, timedelta, timezone
import jwt
from .config import get_settings

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(s), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def _token(sub: str, kind: str, ttl: timedelta, secret: str, **extra) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": sub, "typ": kind, "jti": uuid.uuid4().hex, "iat": now, "exp": now + ttl, **extra},
                      secret, algorithm="HS256")


def create_access_token(user_id: str) -> str:
    s = get_settings()
    return _token(user_id, "access", timedelta(minutes=s.access_ttl_min), s.jwt_secret)


def create_refresh_token(user_id: str) -> str:
    s = get_settings()
    return _token(user_id, "refresh", timedelta(days=s.refresh_ttl_days), s.jwt_refresh_secret)


def decode_token(token: str, kind: str) -> str:
    s = get_settings()
    secret = s.jwt_secret if kind == "access" else s.jwt_refresh_secret
    data = jwt.decode(token, secret, algorithms=["HS256"])  # lève jwt.PyJWTError
    if data.get("typ") != kind:
        raise jwt.InvalidTokenError("mauvais type de jeton")
    return data["sub"]


def decode_claims(token: str, kind: str) -> dict:
    s = get_settings()
    data = jwt.decode(token, s.jwt_secret if kind == "access" else s.jwt_refresh_secret, algorithms=["HS256"])
    if data.get("typ") != kind:
        raise jwt.InvalidTokenError("mauvais type de jeton")
    return data


def pw_fingerprint(password_hash: str) -> str:
    """Empreinte liée au mot de passe actuel : un lien de réinitialisation devient invalide après usage."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_action_token(user_id: str, purpose: str, ttl: timedelta, fingerprint: str = "") -> str:
    """Jeton à usage ciblé ('verify_email' | 'reset_password'), signé avec le secret de refresh."""
    return _token(user_id, purpose, ttl, get_settings().jwt_refresh_secret, fp=fingerprint)


def decode_action_token(token: str, purpose: str) -> dict:
    return _decode_purpose(token, purpose)


def _decode_purpose(token: str, purpose: str) -> dict:
    data = jwt.decode(token, get_settings().jwt_refresh_secret, algorithms=["HS256"])
    if data.get("typ") != purpose:
        raise jwt.InvalidTokenError("mauvais type de jeton")
    return data


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
