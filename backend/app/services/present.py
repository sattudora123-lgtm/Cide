from datetime import UTC, datetime

from app.services.state import is_approved, latest_result


def compute_agent_status(agent: dict, steps: list[dict], now: datetime, stale_seconds: int) -> str:
    if agent["disabled"]:
        return "disabled"
    if agent.get("reported_state") == "error":
        return "error"
    last_seen = agent.get("last_heartbeat_at")
    if not last_seen:
        return "offline"
    seen = datetime.fromisoformat(last_seen)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    if (now - seen).total_seconds() > stale_seconds:
        return "offline"
    working = any(
        step["assigned_agent_id"] == agent["id"] and step["status"] in {"assigned", "running", "awaiting_user"}
        for step in steps
    )
    if working or agent.get("reported_state") == "busy":
        return "busy"
    return "idle"


def present_config(config: dict) -> dict:
    return {
        "provider": config.get("provider"),
        "model": config.get("model"),
        "notes": config.get("notes"),
    }


def present_agent(agent: dict, steps: list[dict], now: datetime, stale_seconds: int) -> dict:
    return {
        "id": agent["id"],
        "name": agent["name"],
        "kind": agent["kind"],
        "status": compute_agent_status(agent, steps, now, stale_seconds),
        "capabilities": list(agent["capabilities"]),
        "config": present_config(agent["config"]),
        "last_heartbeat_at": agent.get("last_heartbeat_at"),
        "created_at": agent["created_at"],
        "updated_at": agent["updated_at"],
    }


def present_agent_summary(agent: dict, steps: list[dict], now: datetime, stale_seconds: int) -> dict:
    return {
        "id": agent["id"],
        "name": agent["name"],
        "kind": agent["kind"],
        "status": compute_agent_status(agent, steps, now, stale_seconds),
    }


def present_task(task: dict) -> dict:
    return {
        "id": task["id"],
        "title": task["title"],
        "input_text": task["input_text"],
        "status": task["status"],
        "decomposition": "not_performed",
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


def present_result(result: dict) -> dict:
    return {
        "id": result["id"],
        "output_text": result["output_text"],
        "untrusted": True,
        "error_code": result.get("error_code"),
        "created_at": result["created_at"],
    }


def present_step(db: dict, step: dict, now: datetime, stale_seconds: int) -> dict:
    agent = None
    if step.get("assigned_agent_id"):
        stored = next((item for item in db["agents"] if item["id"] == step["assigned_agent_id"]), None)
        if stored is not None and stored["user_id"] == step["user_id"]:
            agent = present_agent_summary(stored, db["steps"], now, stale_seconds)
    result = latest_result(db, step["id"])
    return {
        "id": step["id"],
        "workflow_id": step["workflow_id"],
        "task_id": step["task_id"],
        "sequence": step["sequence"],
        "title": step["title"],
        "instruction": step["instruction"],
        "status": step["status"],
        "requires_approval": step["requires_approval"],
        "approved": is_approved(db, step["id"]),
        "assigned_agent_id": step.get("assigned_agent_id"),
        "agent": agent,
        "latest_result": present_result(result) if result is not None else None,
    }


def present_event(event: dict) -> dict:
    payload = event.get("payload") or {}
    message = payload.get("message", "")
    return {
        "id": event["id"],
        "seq": event["seq"],
        "task_id": event["task_id"],
        "step_id": event.get("step_id"),
        "agent_id": event.get("agent_id"),
        "direction": event["direction"],
        "event_type": event["event_type"],
        "payload": {"message": str(message)[:180], "untrusted": True},
        "created_at": event["created_at"],
    }


def present_provider(record: dict) -> dict:
    return {
        "id": record["id"],
        "provider": record["provider"],
        "label": record["label"],
        "created_at": record["created_at"],
    }


def present_browser_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "step_id": job["step_id"],
        "task_id": job["task_id"],
        "target_url": job["target_url"],
        "prompt": job["prompt"],
        "status": job["status"],
        "result_text": job.get("result_text"),
        "untrusted": True,
        "created_at": job["created_at"],
        "completed_at": job.get("completed_at"),
    }
