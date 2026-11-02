from app.services.clock import utc_now
from app.services.ids import new_id

_MAX_MESSAGE = 180


def append_event(
    db: dict,
    *,
    user_id: str,
    task_id: str,
    step_id: str | None,
    agent_id: str | None,
    direction: str,
    event_type: str,
    message: str,
) -> dict:
    db["meta"]["event_seq"] = int(db["meta"]["event_seq"]) + 1
    record = {
        "id": new_id(),
        "seq": db["meta"]["event_seq"],
        "user_id": user_id,
        "task_id": task_id,
        "step_id": step_id,
        "agent_id": agent_id,
        "direction": direction,
        "event_type": event_type,
        "payload": {"message": message[:_MAX_MESSAGE], "untrusted": True},
        "created_at": utc_now(),
    }
    db["events"].append(record)
    return record
