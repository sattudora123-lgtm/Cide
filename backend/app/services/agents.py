from app.core.errors import AppError
from app.core.security import generate_token, hash_token
from app.services.clock import utc_now
from app.services.ids import new_id
from app.services.state import get_agent, log_step, refresh_task
from app.services.state import add_result as store_result


def create_agent(db: dict, user_id: str, body) -> dict:
    token = generate_token("cide_agent_")
    now = utc_now()
    agent = {
        "id": new_id(),
        "user_id": user_id,
        "name": body.name.strip(),
        "kind": body.kind,
        "capabilities": list(body.capabilities),
        "config": _config_from_body(body),
        "token_hash": hash_token(token),
        "disabled": False,
        "reported_state": "idle",
        "last_heartbeat_at": None,
        "created_at": now,
        "updated_at": now,
    }
    db["agents"].append(agent)
    return {"id": agent["id"], "token": token}


def update_agent(db: dict, user_id: str, agent_id: str, body) -> dict:
    agent = get_agent(db, user_id, agent_id)
    if body.name is not None:
        agent["name"] = body.name.strip()
    if body.capabilities is not None:
        agent["capabilities"] = list(body.capabilities)
    if body.notes is not None or body.provider is not None or body.model is not None:
        config = dict(agent["config"])
        if body.notes is not None:
            config["notes"] = body.notes.strip()
        if agent["kind"] == "provider_model":
            if body.provider is not None:
                config["provider"] = body.provider
            if body.model is not None:
                if not body.model.strip():
                    raise AppError(422, "validation_error", "Model is required")
                config["model"] = body.model.strip()
        elif body.provider is not None or body.model is not None:
            raise AppError(422, "validation_error", "provider and model are only valid for provider models")
        agent["config"] = config
    agent["updated_at"] = utc_now()
    return agent


def disable_agent(db: dict, user_id: str, agent_id: str) -> dict:
    agent = get_agent(db, user_id, agent_id)
    agent["disabled"] = True
    agent["updated_at"] = utc_now()
    return agent


def rotate_agent_token(db: dict, user_id: str, agent_id: str) -> str:
    agent = get_agent(db, user_id, agent_id)
    token = generate_token("cide_agent_")
    agent["token_hash"] = hash_token(token)
    agent["updated_at"] = utc_now()
    return token


def record_heartbeat(db: dict, agent_id: str, state: str) -> dict:
    agent = next((item for item in db["agents"] if item["id"] == agent_id), None)
    if agent is None or agent["disabled"]:
        raise AppError(403, "agent_disabled", "This agent is disabled")
    agent["last_heartbeat_at"] = utc_now()
    agent["reported_state"] = state
    agent["updated_at"] = agent["last_heartbeat_at"]
    return agent


def list_assignments(db: dict, agent: dict) -> list[dict]:
    rows = [
        step
        for step in db["steps"]
        if step["assigned_agent_id"] == agent["id"]
        and step["user_id"] == agent["user_id"]
        and step["status"] in {"assigned", "running"}
    ]
    rows.sort(key=lambda step: (step["created_at"], step["id"]))
    return [
        {
            "step_id": step["id"],
            "task_id": step["task_id"],
            "title": step["title"],
            "instruction": step["instruction"],
            "status": step["status"],
            "sequence": step["sequence"],
            "created_at": step["created_at"],
            "id": step["id"],
        }
        for step in rows
    ]


def accept_agent_event(db: dict, agent: dict, body) -> dict:
    step = next(
        (
            item
            for item in db["steps"]
            if item["id"] == str(body.step_id) and item["assigned_agent_id"] == agent["id"] and item["user_id"] == agent["user_id"]
        ),
        None,
    )
    if step is None:
        raise AppError(404, "step_not_found", "Step not found")
    if step["status"] not in {"assigned", "running"}:
        raise AppError(409, "invalid_step_state", "This step is not accepting agent updates")
    if body.event_type == "progress":
        step["status"] = "running"
        log_step(db, step, event_type="progress", direction="agent_to_host", message=body.message or "Progress reported", agent_id=agent["id"])
    elif body.event_type == "log":
        log_step(db, step, event_type="log", direction="agent_to_host", message=body.message or "Log reported", agent_id=agent["id"])
    elif body.event_type == "result":
        store_result(
            db,
            user_id=step["user_id"],
            step=step,
            agent_id=agent["id"],
            output_text=body.output_text or "",
            error_code=None,
        )
        step["status"] = "completed"
        log_step(db, step, event_type="result", direction="agent_to_host", message=body.message or "Result submitted", agent_id=agent["id"])
    elif body.event_type == "error":
        store_result(
            db,
            user_id=step["user_id"],
            step=step,
            agent_id=agent["id"],
            output_text=body.output_text or body.message or "",
            error_code=body.error_code,
        )
        step["status"] = "failed"
        log_step(db, step, event_type="error", direction="agent_to_host", message=body.message or body.error_code or "Agent reported an error", agent_id=agent["id"])
    else:
        raise AppError(422, "validation_error", "Event type is invalid")
    step["updated_at"] = utc_now()
    refresh_task(db, step["task_id"])
    return step


def _config_from_body(body) -> dict:
    config = {}
    if getattr(body, "provider", None):
        config["provider"] = body.provider
    if getattr(body, "model", None) and body.model.strip():
        config["model"] = body.model.strip()
    if getattr(body, "notes", None) and body.notes.strip():
        config["notes"] = body.notes.strip()
    return config
