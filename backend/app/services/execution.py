"""Dispatch seam. Installed agents poll; this module never starts a process."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.chat import ProviderError, ProviderTimeout, complete_chat
from app.services.clock import utc_now
from app.services.providers import find_provider
from app.services.secrets import decrypt_secret
from app.services.state import add_result, get_agent, get_step, is_approved, log_step, refresh_task
from app.storage.vault import EncryptedJsonStore


async def dispatch(
    *,
    store: EncryptedJsonStore,
    settings: Settings,
    http: httpx.AsyncClient,
    user_id: str,
    step_id: str,
) -> None:
    """Do not call this while a store transaction is already open."""
    prepared = _prepare(store, settings, user_id, step_id)
    if prepared is None:
        return
    provider, model, api_key, instruction = prepared
    try:
        try:
            output = await complete_chat(
                http,
                provider=provider,
                model=model,
                api_key=api_key,
                instruction=instruction,
                max_tokens=settings.provider_max_tokens,
            )
        except ProviderTimeout:
            _finish_provider(store, user_id, step_id, error_code="provider_timeout", output_text="")
            raise AppError(504, "provider_timeout", "The provider did not respond in time") from None
        except ProviderError:
            _finish_provider(store, user_id, step_id, error_code="provider_request_failed", output_text="")
            raise AppError(502, "provider_request_failed", "The provider request failed") from None
    finally:
        del api_key
    _finish_provider(store, user_id, step_id, error_code=None, output_text=output)


def _prepare(store: EncryptedJsonStore, settings: Settings, user_id: str, step_id: str):
    with store.transaction() as db:
        step = get_step(db, user_id, step_id)
        if not step.get("assigned_agent_id"):
            raise AppError(409, "agent_not_assigned", "Assign an agent before dispatch")
        agent = get_agent(db, user_id, step["assigned_agent_id"])
        allowed = {"pending", "assigned"}
        if agent["kind"] == "browser_model":
            allowed.add("awaiting_user")
        if step["status"] not in allowed:
            raise AppError(409, "invalid_step_state", "Step cannot be dispatched from its current status")
        if step["requires_approval"] and not is_approved(db, step["id"]):
            raise AppError(409, "approval_required", "This step requires approval before dispatch")
        if agent["disabled"]:
            raise AppError(409, "agent_disabled", "The assigned agent is disabled")
        kind = agent["kind"]
        if kind in {"installed_agent", "webhook_agent"}:
            if step["status"] == "assigned":
                return None
            step["status"] = "assigned"
            step["updated_at"] = utc_now()
            log_step(
                db,
                step,
                event_type="assignment",
                direction="host_to_agent",
                message="Step assigned. The agent must poll for this work.",
                agent_id=agent["id"],
            )
            refresh_task(db, step["task_id"])
            return None
        if kind == "browser_model":
            open_job = next(
                (
                    job
                    for job in db["browser_jobs"]
                    if job["step_id"] == step["id"] and job["status"] == "awaiting_user"
                ),
                None,
            )
            if open_job is None:
                raise AppError(409, "browser_target_required", "Create a browser job before dispatch")
            if step["status"] == "awaiting_user":
                return None
            step["status"] = "awaiting_user"
            step["updated_at"] = utc_now()
            log_step(
                db,
                step,
                event_type="log",
                direction="system",
                message="Waiting for the user to submit the browser result",
            )
            refresh_task(db, step["task_id"])
            return None
        if kind != "provider_model":
            raise AppError(409, "unsupported_agent", "This agent kind cannot be dispatched")
        provider_name = agent["config"].get("provider")
        model = agent["config"].get("model")
        if not provider_name or not model:
            raise AppError(409, "provider_not_configured", "This agent has no provider model configured")
        connection = find_provider(db, user_id, provider_name)
        if connection is None:
            raise AppError(409, "provider_not_configured", "No API key is stored for this provider")
        api_key = decrypt_secret(settings.token_encryption_key, connection["api_key_encrypted"])
        step["status"] = "running"
        step["updated_at"] = utc_now()
        log_step(db, step, event_type="progress", direction="system", message="Provider request started", agent_id=agent["id"])
        refresh_task(db, step["task_id"])
        return provider_name, model, api_key, step["instruction"]


def _finish_provider(
    store: EncryptedJsonStore,
    user_id: str,
    step_id: str,
    *,
    error_code: str | None,
    output_text: str,
) -> None:
    with store.transaction() as db:
        step = get_step(db, user_id, step_id)
        if step["status"] != "running":
            raise AppError(409, "invalid_step_state", "Step changed before the provider finished")
        add_result(
            db,
            user_id=user_id,
            step=step,
            agent_id=step.get("assigned_agent_id"),
            output_text=output_text,
            error_code=error_code,
        )
        step["status"] = "failed" if error_code else "completed"
        step["updated_at"] = utc_now()
        log_step(
            db,
            step,
            event_type="error" if error_code else "result",
            direction="system",
            message=error_code or "Provider result stored",
            agent_id=step.get("assigned_agent_id"),
        )
        refresh_task(db, step["task_id"])
