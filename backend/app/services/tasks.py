import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from app.core.errors import AppError
from app.services.clock import parse_time, utc_now
from app.services.events import append_event
from app.services.ids import new_id
from app.services.present import present_agent_summary, present_event, present_step, present_task
from app.services.state import (
    get_agent,
    get_step,
    get_task,
    is_approved,
    latest_workflow,
    log_step,
    record_approval,
    refresh_task,
    workflow_steps,
)

_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)


def create_task(db: dict, user_id: str, body, idempotency_key: str | None, now: datetime) -> dict:
    _drop_expired_keys(db, user_id, now)
    digest = _request_hash(body.title.strip(), body.input_text)
    if idempotency_key is not None:
        if not _IDEMPOTENCY.fullmatch(idempotency_key):
            raise AppError(400, "invalid_idempotency_key", "Idempotency-Key is invalid")
        existing = next(
            (item for item in db["idempotency_keys"] if item["user_id"] == user_id and item["key"] == idempotency_key),
            None,
        )
        if existing is not None:
            if existing["request_hash"] != digest:
                raise AppError(409, "idempotency_conflict", "This Idempotency-Key was used for a different request")
            return present_task(get_task(db, user_id, existing["task_id"]))
    timestamp = utc_now()
    task = {
        "id": new_id(),
        "user_id": user_id,
        "title": body.title.strip(),
        "input_text": body.input_text,
        "status": "queued",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    db["tasks"].append(task)
    if idempotency_key is not None:
        db["idempotency_keys"].append(
            {
                "id": new_id(),
                "user_id": user_id,
                "key": idempotency_key,
                "task_id": task["id"],
                "request_hash": digest,
                "created_at": timestamp,
            }
        )
    return present_task(task)


def create_workflow(db: dict, user_id: str, task_id: str, body, now: datetime, stale_seconds: int) -> dict:
    task = get_task(db, user_id, task_id)
    if task["status"] == "cancelled":
        raise AppError(409, "invalid_task_state", "Task is cancelled")
    current = latest_workflow(db, task_id)
    if current is not None:
        statuses = {step["status"] for step in workflow_steps(db, current["id"])}
        if not statuses or not statuses <= {"completed", "failed", "cancelled"}:
            raise AppError(409, "workflow_exists", "This task already has an open workflow")
    timestamp = utc_now()
    workflow = {
        "id": new_id(),
        "task_id": task["id"],
        "user_id": user_id,
        "version": 1 if current is None else current["version"] + 1,
        "status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    db["workflows"].append(workflow)
    for index, item in enumerate(body.steps, start=1):
        assigned = None
        if item.assigned_agent_id is not None:
            agent = get_agent(db, user_id, str(item.assigned_agent_id))
            if agent["disabled"]:
                raise AppError(409, "agent_disabled", "The assigned agent is disabled")
            assigned = agent["id"]
        status = "awaiting_approval" if item.requires_approval else "pending"
        db["steps"].append(
            {
                "id": new_id(),
                "workflow_id": workflow["id"],
                "task_id": task["id"],
                "user_id": user_id,
                "sequence": index,
                "title": item.title.strip(),
                "instruction": item.instruction,
                "status": status,
                "requires_approval": item.requires_approval,
                "assigned_agent_id": assigned,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
    refresh_task(db, task["id"])
    return _workflow_body(db, workflow, now, stale_seconds)


def assign_step(db: dict, user_id: str, step_id: str, agent_id: str, now: datetime, stale_seconds: int) -> dict:
    step = get_step(db, user_id, step_id)
    if step["status"] not in {"pending", "awaiting_approval"}:
        raise AppError(409, "invalid_step_state", "Step can no longer be assigned")
    agent = get_agent(db, user_id, agent_id)
    if agent["disabled"]:
        raise AppError(409, "agent_disabled", "The assigned agent is disabled")
    step["assigned_agent_id"] = agent["id"]
    if step["requires_approval"] and not is_approved(db, step["id"]):
        step["status"] = "awaiting_approval"
    step["updated_at"] = utc_now()
    log_step(
        db,
        step,
        event_type="assignment",
        direction="system",
        message="Agent selected for this step",
        agent_id=agent["id"],
    )
    return present_step(db, step, now, stale_seconds)


def approve_step(db: dict, user_id: str, step_id: str, now: datetime, stale_seconds: int) -> dict:
    step = _approval_target(db, user_id, step_id)
    record_approval(db, user_id=user_id, step_id=step["id"], status="approved")
    step["status"] = "pending"
    step["updated_at"] = utc_now()
    log_step(db, step, event_type="log", direction="system", message="Step approved")
    return present_step(db, step, now, stale_seconds)


def deny_step(db: dict, user_id: str, step_id: str, now: datetime, stale_seconds: int) -> dict:
    step = _approval_target(db, user_id, step_id)
    record_approval(db, user_id=user_id, step_id=step["id"], status="denied")
    step["status"] = "cancelled"
    step["updated_at"] = utc_now()
    log_step(db, step, event_type="log", direction="system", message="Step denied")
    refresh_task(db, step["task_id"])
    return present_step(db, step, now, stale_seconds)


def cancel_task(db: dict, user_id: str, task_id: str) -> dict:
    task = get_task(db, user_id, task_id)
    if task["status"] in {"completed", "cancelled"}:
        raise AppError(409, "invalid_task_state", "Task can no longer be cancelled")
    now = utc_now()
    task["status"] = "cancelled"
    task["updated_at"] = now
    workflow = latest_workflow(db, task["id"])
    if workflow is not None:
        for step in workflow_steps(db, workflow["id"]):
            if step["status"] not in {"completed", "failed", "cancelled"}:
                step["status"] = "cancelled"
                step["updated_at"] = now
        workflow["status"] = "cancelled"
        workflow["updated_at"] = now
    for job in db["browser_jobs"]:
        if job["user_id"] == user_id and job["task_id"] == task["id"] and job["status"] == "awaiting_user":
            job["status"] = "cancelled"
    append_event(
        db,
        user_id=user_id,
        task_id=task["id"],
        step_id=None,
        agent_id=None,
        direction="system",
        event_type="log",
        message="Task cancelled",
    )
    return present_task(task)


def task_detail(db: dict, user_id: str, task_id: str, now: datetime, stale_seconds: int) -> dict:
    task = get_task(db, user_id, task_id)
    workflow = latest_workflow(db, task["id"])
    events = [item for item in db["events"] if item["user_id"] == user_id and item["task_id"] == task["id"]]
    events.sort(key=lambda item: item["seq"])
    recent = [present_event(item) for item in events[-20:]]
    if workflow is None:
        return {"task": present_task(task), "workflow": None, "agents": [], "recent_events": recent}
    steps = workflow_steps(db, workflow["id"])
    presented_steps = [present_step(db, step, now, stale_seconds) for step in steps]
    agents = []
    seen = set()
    for step in steps:
        if not step.get("assigned_agent_id") or step["assigned_agent_id"] in seen:
            continue
        stored = next((item for item in db["agents"] if item["id"] == step["assigned_agent_id"]), None)
        if stored is None:
            continue
        seen.add(stored["id"])
        agents.append(present_agent_summary(stored, db["steps"], now, stale_seconds))
    return {
        "task": present_task(task),
        "workflow": {
            "id": workflow["id"],
            "version": workflow["version"],
            "status": workflow["status"],
            "steps": presented_steps,
        },
        "agents": agents,
        "recent_events": recent,
    }


def list_events(db: dict, user_id: str, task_id: str, *, after: int, limit: int) -> dict:
    get_task(db, user_id, task_id)
    rows = [
        item
        for item in db["events"]
        if item["user_id"] == user_id and item["task_id"] == task_id and item["seq"] > after
    ]
    rows.sort(key=lambda item: item["seq"])
    page = rows[:limit]
    next_cursor = page[-1]["seq"] if len(rows) > limit else None
    return {"items": [present_event(item) for item in page], "next_cursor": next_cursor}


def _approval_target(db: dict, user_id: str, step_id: str) -> dict:
    step = get_step(db, user_id, step_id)
    if not step["requires_approval"]:
        raise AppError(409, "approval_not_required", "This step does not require approval")
    if step["status"] != "awaiting_approval":
        raise AppError(409, "invalid_step_state", "This step is not awaiting approval")
    return step


def _request_hash(title: str, input_text: str) -> str:
    raw = json.dumps({"input_text": input_text, "title": title}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _drop_expired_keys(db: dict, user_id: str, now: datetime) -> None:
    cutoff = now - _IDEMPOTENCY_TTL
    db["idempotency_keys"] = [
        item
        for item in db["idempotency_keys"]
        if item["user_id"] != user_id or parse_time(item["created_at"]) >= cutoff
    ]


def _workflow_body(db: dict, workflow: dict, now: datetime, stale_seconds: int) -> dict:
    steps = workflow_steps(db, workflow["id"])
    return {
        "id": workflow["id"],
        "version": workflow["version"],
        "status": workflow["status"],
        "steps": [present_step(db, step, now, stale_seconds) for step in steps],
    }
