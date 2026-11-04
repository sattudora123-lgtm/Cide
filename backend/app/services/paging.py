import base64

from app.core.errors import AppError


def encode_cursor(created_at: str, record_id: str) -> str:
    raw = f"{created_at}\n{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        created_at, record_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split("\n", 1)
    except Exception as exc:
        raise AppError(400, "invalid_cursor", "Cursor is invalid") from exc
    if not created_at or not record_id:
        raise AppError(400, "invalid_cursor", "Cursor is invalid")
    return created_at, record_id


def paginate_desc(rows: list[dict], *, cursor: str | None, limit: int) -> tuple[list[dict], str | None]:
    ordered = sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)
    if cursor:
        marker = decode_cursor(cursor)
        ordered = [row for row in ordered if (row["created_at"], row["id"]) < marker]
    page = ordered[:limit]
    next_cursor = encode_cursor(page[-1]["created_at"], page[-1]["id"]) if len(ordered) > limit else None
    return page, next_cursor
