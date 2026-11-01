import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.errors import AppError

_HASHER = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hashes_match(stored_hash: str, raw_token: str) -> bool:
    if len(stored_hash) != 64:
        return False
    return hmac.compare_digest(stored_hash, hash_token(raw_token))


def create_access_token(secret: str, user_id: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(secret: str, token: str) -> str:
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AppError(401, "invalid_access_token", "Access token is invalid or expired") from exc
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise AppError(401, "invalid_access_token", "Access token is invalid or expired")
    return payload["sub"]
