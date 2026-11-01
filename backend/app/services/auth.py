from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.errors import AppError, CommitAndRaise
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    hashes_match,
    verify_password,
)
from app.services.clock import parse_time, utc_now
from app.services.ids import new_id


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "is_active": user["is_active"],
    }


def register_user(db: dict, *, email: str, password: str, display_name: str) -> dict:
    if any(user["email"] == email for user in db["users"]):
        raise AppError(409, "email_taken", "An account with this email already exists")
    now = utc_now()
    user = {
        "id": new_id(),
        "email": email,
        "display_name": display_name,
        "password_hash": hash_password(password),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    db["users"].append(user)
    return public_user(user)


def login_user(db: dict, settings: Settings, *, email: str, password: str, dummy_password_hash: str) -> dict:
    user = next((item for item in db["users"] if item["email"] == email), None)
    if user is None or not user["is_active"] or not verify_password(password, user["password_hash"]):
        verify_password(password, dummy_password_hash)
        raise AppError(401, "invalid_credentials", "Invalid email or password")
    return _issue_tokens(db, settings, user["id"])


def refresh_session(db: dict, settings: Settings, raw_token: str) -> dict:
    row = _find_refresh_token(db, raw_token)
    if row is None:
        raise AppError(401, "invalid_refresh_token", "Refresh token is invalid")
    if row["revoked_at"] is not None:
        _revoke_all(db, row["user_id"])
        raise CommitAndRaise(AppError(401, "refresh_token_reused", "Refresh token reuse was detected"))
    if parse_time(row["expires_at"]) <= datetime.now(UTC):
        row["revoked_at"] = utc_now()
        raise CommitAndRaise(AppError(401, "refresh_token_expired", "Refresh token is expired"))
    user = next((item for item in db["users"] if item["id"] == row["user_id"]), None)
    if user is None or not user["is_active"]:
        row["revoked_at"] = utc_now()
        raise CommitAndRaise(AppError(401, "invalid_refresh_token", "Refresh token is invalid"))
    row["revoked_at"] = utc_now()
    return _issue_tokens(db, settings, user["id"])


def logout_session(db: dict, user_id: str, raw_token: str) -> None:
    row = _find_refresh_token(db, raw_token)
    if row is None or row["user_id"] != user_id:
        raise AppError(401, "invalid_refresh_token", "Refresh token is invalid")
    if row["revoked_at"] is None:
        row["revoked_at"] = utc_now()


def _issue_tokens(db: dict, settings: Settings, user_id: str) -> dict:
    raw_refresh = generate_token("cide_refresh_")
    now = datetime.now(UTC)
    db["refresh_tokens"].append(
        {
            "id": new_id(),
            "user_id": user_id,
            "token_hash": hash_token(raw_refresh),
            "expires_at": (now + timedelta(seconds=settings.jwt_refresh_ttl_seconds)).isoformat(),
            "revoked_at": None,
            "created_at": now.isoformat(),
        }
    )
    return {
        "access_token": create_access_token(settings.jwt_secret, user_id, settings.jwt_access_ttl_seconds),
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_ttl_seconds,
    }


def _find_refresh_token(db: dict, raw_token: str) -> dict | None:
    for row in db["refresh_tokens"]:
        if hashes_match(row["token_hash"], raw_token):
            return row
    return None


def _revoke_all(db: dict, user_id: str) -> None:
    now = utc_now()
    for row in db["refresh_tokens"]:
        if row["user_id"] == user_id and row["revoked_at"] is None:
            row["revoked_at"] = now
