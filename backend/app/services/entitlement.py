from datetime import UTC, datetime

from app.services.clock import parse_time

_TRIAL_STATUSES = {"trial", "approval_pending", "cancelled"}


def access_allowed(user: dict, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    if user.get("complimentary"):
        return True
    status = user.get("subscription_status")
    if status == "active":
        return True
    if status in {"suspended", "expired"}:
        return False
    trial_ends = user.get("trial_ends_at")
    if status in _TRIAL_STATUSES and trial_ends and parse_time(trial_ends) > current:
        return True
    return False


def present_subscription(user: dict, now: datetime | None = None) -> dict:
    current = now or datetime.now(UTC)
    status = user.get("subscription_status") or "expired"
    trial_ends = user.get("trial_ends_at")
    if status == "trial" and trial_ends and parse_time(trial_ends) <= current:
        status = "expired"
    allowed = access_allowed(user, current)
    return {
        "status": status,
        "access": "allowed" if allowed else "payment_required",
        "trial_ends_at": trial_ends,
        "complimentary": bool(user.get("complimentary")),
    }
