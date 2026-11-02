from app.core.errors import AppError
from app.services.clock import utc_now
from app.services.events import append_event
from app.services.ids import new_id

ACTIVE_STEP_STATUSES = {"assigned", "running", "awaiting_user"}
OUTPUT_LIMIT = 100_000


def require_user(db: dict, user_id: str) -> dict:
    user = next((item for item in db["users"] if item["id"] == user_id), None)
    if user is None or not user["is_active"]:
        raise AppError(401, "invalid_access_token", "Access token is invalid or expired")
    return user


def get_task(db: dict, user_id: str, task_id: str) -> dict:
    task = next((item for item in db["tasks"] if item["id"] == task_id and item["user_id"] == user_id), None)
    if task is None:
        raise AppError(404, "task_not_found", "Task not found")
    return task


def get_step(db: dict, user_id: str, step_id: str) -> dict:
    step = next((item for item in db["steps"] if item["id"] == step_id and item["user_id"] == user_id), None)
    if step is None:
        raise AppError(404, "step_not_found", "Step not found")
    return step


def get_agent(db: dict, user_id: str, agent_id: str) -> dict:
    agent = next((item for item in db["agents"] if item["id"] == agent_id and item["user_id"] == user_id), None)
    if agent is None:
        raise AppError(404, "agent_not_found", "Agent not found")
    return agent


def latest_workflow(db: dict, task_id: str) -> dict | None:
    rows = [item for item in db["workflows"] if item["task_id"] == task_id]
    if not rows:
        return None
    return max(rows, key=lambda item: item["version"])


def workflow_steps(db: dict, workflow_id: str) -> list[dict]:
    rows = [item for item in db["steps"] if item["workflow_id"] == workflow_id]
    rows.sort(key=lambda item: item["sequence"])
    return rows


def latest_approval(db: dict, step_id: str) -> dict | None:
    rows = [item for item in db["approvals"] if item["step_id"] == step_id]
    if not rows:
        return None
    return max(rows, key=lambda item: item["created_at"])


def is_approved(db: dict, step_id: str) -> bool:
    approval = latest_approval(db, step_id)
    return approval is not None and approval["status"] == "approved"


def derive_workflow_status(steps: list[dict]) -> str:
    statuses = [step["status"] for step in steps]
    if not statuses:
        return "pending"
    if all(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status == "failed" for status in statuses):
        return "failed"
    remaining = [status for status in statuses if status != "cancelled"]
    if remaining and all(status == "completed" for status in remaining):
        return "completed"
    if any(status in ACTIVE_STEP_STATUSES for status in statuses):
        return "running"
    return "pending"


def refresh_task(db: dict, task_id: str) -> None:
    task = next(item for item in db["tasks"] if item["id"] == task_id)
    now = utc_now()
    workflow = latest_workflow(db, task_id)
    if task["status"] == "cancelled":
        if workflow is not None:
            workflow["status"] = "cancelled"
            workflow["updated_at"] = now
        return
    if workflow is None:
        task["status"] = "queued"
        task["updated_at"] = now
        return
    status = derive_workflow_status(workflow_steps(db, workflow["id"]))
    workflow["status"] = status
    workflow["updated_at"] = now
    if status == "pending":
        task["status"] = "queued"
    else:
        task["status"] = status
    task["updated_at"] = now


def bound_text(value: str) -> str:
    if len(value) <= OUTPUT_LIMIT:
        return value
    return value[:OUTPUT_LIMIT] + "\n[truncated]"


def add_result(
    db: dict,
    *,
    user_id: str,
    step: dict,
    agent_id: str | None,
    output_text: str,
    error_code: str | None,
) -> dict:
    record = {
        "id": new_id(),
        "user_id": user_id,
        "step_id": step["id"],
        "task_id": step["task_id"],
        "agent_id": agent_id,
        "output_text": bound_text(output_text),
        "error_code": error_code,
        "created_at": utc_now(),
    }
    db["results"].append(record)
    return record


def latest_result(db: dict, step_id: str) -> dict | None:
    rows = [item for item in db["results"] if item["step_id"] == step_id]
    if not rows:
        return None
    return max(rows, key=lambda item: (item["created_at"], item["id"]))


def record_approval(db: dict, *, user_id: str, step_id: str, status: str) -> None:
    now = utc_now()
    db["approvals"].append(
        {
            "id": new_id(),
            "user_id": user_id,
            "step_id": step_id,
            "status": status,
            "created_at": now,
            "decided_at": now,
        }
    )


def log_step(
    db: dict,
    step: dict,
    *,
    event_type: str,
    direction: str,
    message: str,
    agent_id: str | None = None,
) -> None:
    append_event(
        db,
        user_id=step["user_id"],
        task_id=step["task_id"],
        step_id=step["id"],
        agent_id=agent_id if agent_id is not None else step.get("assigned_agent_id"),
        direction=direction,
        event_type=event_type,
        message=message,
    )
