from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.schemas.models import HealthStatus
from app.storage.errors import StorageError, StorageIntegrityError

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthStatus)
def health() -> dict:
    return {"status": "ok"}


@router.get("/ready", response_model=HealthStatus)
def ready(request: Request) -> dict:
    try:
        with request.app.state.store.transaction():
            return {"status": "ready"}
    except StorageIntegrityError as exc:
        raise AppError(503, "storage_integrity_error", "Encrypted storage failed integrity checks") from exc
    except StorageError as exc:
        raise AppError(503, "storage_unavailable", "Encrypted storage is unavailable") from exc
