from datetime import UTC, datetime


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
