import os
os.environ.setdefault("JWT_SECRET", "t" * 40)
os.environ.setdefault("JWT_REFRESH_SECRET", "r" * 40)
import jwt, pytest
from app.core.security import (create_access_token, create_refresh_token, decode_token,
                               hash_password, verify_password)


def test_password_roundtrip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) and not verify_password("nope", h)


def test_refresh_token_not_accepted_as_access():
    with pytest.raises(jwt.PyJWTError):
        decode_token(create_refresh_token("u1"), "access")


def test_access_roundtrip():
    assert decode_token(create_access_token("u1"), "access") == "u1"
