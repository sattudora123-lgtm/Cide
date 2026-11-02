"""Collection names stored as separate encrypted JSON documents."""

from __future__ import annotations

COLLECTIONS = (
    "users",
    "refresh_tokens",
    "agents",
    "tasks",
    "workflows",
    "steps",
    "results",
    "events",
    "approvals",
    "providers",
    "browser_jobs",
    "idempotency_keys",
)


def empty_db() -> dict:
    database = {name: [] for name in COLLECTIONS}
    database["meta"] = {"event_seq": 0, "generation": 0}
    return database
