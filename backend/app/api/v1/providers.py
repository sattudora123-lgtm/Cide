from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_current_user, list_params
from app.schemas.models import ProviderCreate, ProviderPage, ProviderPublic
from app.services.paging import paginate_desc
from app.services.present import present_provider
from app.services.providers import delete_provider, save_provider
from app.services.state import require_user

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("", status_code=201, response_model=ProviderPublic)
def create(body: ProviderCreate, request: Request, user: dict = Depends(get_current_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return save_provider(db, request.app.state.settings, user["id"], body)


@router.get("", response_model=ProviderPage)
def list_providers(
    request: Request,
    user: dict = Depends(get_current_user),
    page: tuple[int, str | None] = Depends(list_params),
) -> dict:
    limit, cursor = page
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        rows = [present_provider(item) for item in db["providers"] if item["user_id"] == user["id"]]
        selected, next_cursor = paginate_desc(rows, cursor=cursor, limit=limit)
        return {"items": selected, "next_cursor": next_cursor}


@router.delete("/{provider_id}", status_code=204)
def delete(provider_id: UUID, request: Request, user: dict = Depends(get_current_user)) -> Response:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        delete_provider(db, user["id"], str(provider_id))
    return Response(status_code=204)
