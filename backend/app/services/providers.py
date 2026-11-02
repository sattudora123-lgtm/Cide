from app.core.config import Settings
from app.core.errors import AppError
from app.services.clock import utc_now
from app.services.ids import new_id
from app.services.present import present_provider
from app.services.secrets import encrypt_secret


def save_provider(db: dict, settings: Settings, user_id: str, body) -> dict:
    if any(item["user_id"] == user_id and item["provider"] == body.provider for item in db["providers"]):
        raise AppError(409, "provider_exists", "A connection for this provider already exists")
    record = {
        "id": new_id(),
        "user_id": user_id,
        "provider": body.provider,
        "label": body.label.strip(),
        "api_key_encrypted": encrypt_secret(settings.token_encryption_key, body.api_key),
        "created_at": utc_now(),
    }
    db["providers"].append(record)
    return present_provider(record)


def delete_provider(db: dict, user_id: str, provider_id: str) -> None:
    record = next((item for item in db["providers"] if item["id"] == provider_id and item["user_id"] == user_id), None)
    if record is None:
        raise AppError(404, "provider_not_found", "Provider connection not found")
    db["providers"] = [item for item in db["providers"] if item["id"] != record["id"]]


def find_provider(db: dict, user_id: str, provider_name: str) -> dict | None:
    return next(
        (item for item in db["providers"] if item["user_id"] == user_id and item["provider"] == provider_name),
        None,
    )
