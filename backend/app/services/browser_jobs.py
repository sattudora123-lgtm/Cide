from urllib.parse import urlparse

from app.core.errors import AppError
from app.services.clock import utc_now
from app.services.ids import new_id
from app.services.present import present_browser_job
from app.services.state import add_result, bound_text, get_step, is_approved, log_step, refresh_task

ALLOWED_HOSTS = frozenset(
    {
        "chatgpt.com",
        "www.chatgpt.com",
        "claude.ai",
        "www.claude.ai",
        "gemini.google.com",
    }
)


def validate_target_url(url: str) -> str:
    candidate = url.strip()
    if len(candidate) > 2000 or "\\" in candidate or "\n" in candidate or "\r" in candidate:
        raise AppError(422, "invalid_target_url", "Browser target must be an allowlisted https URL")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or host not in ALLOWED_HOSTS
        or parsed.port not in (None, 443)
    ):
        raise AppError(422, "invalid_target_url", "Browser target must be an allowlisted https URL")
    return candidate


def create_browser_job(db: dict, user_id: str, body) -> dict:
    target = validate_target_url(body.target_url)
    step = get_step(db, user_id, str(body.step_id))
    _require_browser_step(db, step)
    if any(job["step_id"] == step["id"] and job["status"] == "awaiting_user" for job in db["browser_jobs"]):
        raise AppError(409, "browser_job_exists", "This step already has an open browser job")
    now = utc_now()
    job = {
        "id": new_id(),
        "user_id": user_id,
        "step_id": step["id"],
        "task_id": step["task_id"],
        "target_url": target,
        "prompt": body.prompt,
        "status": "awaiting_user",
        "result_text": None,
        "created_at": now,
        "completed_at": None,
    }
    db["browser_jobs"].append(job)
    step["status"] = "awaiting_user"
    step["updated_at"] = now
    log_step(db, step, event_type="log", direction="system", message="Browser job is waiting for the user")
    refresh_task(db, step["task_id"])
    return present_browser_job(job)


def submit_browser_result(db: dict, user_id: str, job_id: str, content: str) -> dict:
    job = next((item for item in db["browser_jobs"] if item["id"] == job_id and item["user_id"] == user_id), None)
    if job is None:
        raise AppError(404, "browser_job_not_found", "Browser job not found")
    if job["status"] != "awaiting_user":
        raise AppError(409, "invalid_browser_job_state", "This browser job is not awaiting a result")
    step = get_step(db, user_id, job["step_id"])
    now = utc_now()
    job["status"] = "completed"
    job["result_text"] = bound_text(content)
    job["completed_at"] = now
    add_result(db, user_id=user_id, step=step, agent_id=step.get("assigned_agent_id"), output_text=content, error_code=None)
    step["status"] = "completed"
    step["updated_at"] = now
    log_step(db, step, event_type="result", direction="system", message="User submitted a browser result")
    refresh_task(db, step["task_id"])
    return present_browser_job(job)


def _require_browser_step(db: dict, step: dict) -> None:
    if step["status"] not in {"pending", "assigned"}:
        raise AppError(409, "invalid_step_state", "This step cannot accept a browser job")
    if not step.get("assigned_agent_id"):
        raise AppError(409, "agent_not_assigned", "Assign a browser agent before creating a browser job")
    if step["requires_approval"] and not is_approved(db, step["id"]):
        raise AppError(409, "approval_required", "This step requires approval before a browser job")
    agent = next((item for item in db["agents"] if item["id"] == step["assigned_agent_id"]), None)
    if agent is None or agent["user_id"] != step["user_id"] or agent["kind"] != "browser_model" or agent["disabled"]:
        raise AppError(409, "wrong_agent_kind", "The assigned agent is not an available browser agent")
