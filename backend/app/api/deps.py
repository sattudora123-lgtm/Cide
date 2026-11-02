import hmac
from datetime import UTC, datetime

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.security import decode_access_token, hash_token, hashes_match
from app.services.auth import public_user
from app.services.entitlement import access_allowed
from app.services.state import require_user

bearer = HTTPBearer(auto_error=False)
_DUMMY_AGENT_HASH = hash_token("cide-agent-dummy")


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if creds is None or not creds.credentials:
        raise AppError(401, "not_authenticated", "Authentication is required")
    user_id = decode_access_token(request.app.state.settings.jwt_secret, creds.credentials)
    with request.app.state.store.transaction() as db:
        user = require_user(db, user_id)
        return public_user(user)


def require_entitled_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    user = get_current_user(request, creds)
    if user["subscription"]["access"] != "allowed":
        raise AppError(402, "subscription_required", "A free trial or an active PayPal subscription is required")
    return user


def get_current_agent(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if creds is None or not creds.credentials:
        raise AppError(401, "not_authenticated", "Authentication is required")
    with request.app.state.store.transaction() as db:
        agent = next((item for item in db["agents"] if hashes_match(item["token_hash"], creds.credentials)), None)
        if agent is None:
            hmac.compare_digest(_DUMMY_AGENT_HASH, hash_token(creds.credentials))
            raise AppError(401, "invalid_agent_token", "Agent token is invalid")
        if agent["disabled"]:
            raise AppError(403, "agent_disabled", "This agent is disabled")
        return {"id": agent["id"], "user_id": agent["user_id"], "kind": agent["kind"], "name": agent["name"]}


def require_entitled_agent(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    agent = get_current_agent(request, creds)
    with request.app.state.store.transaction() as db:
        owner = require_user(db, agent["user_id"])
        if not access_allowed(owner, datetime.now(UTC)):
            raise AppError(402, "subscription_required", "A free trial or an active PayPal subscription is required")
    return agent


def list_params(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> tuple[int, str | None]:
    return limit, cursor


def client_host(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host
