import json

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.schemas.models import CheckoutResponse, SubscriptionPublic
from app.services.billing import apply_webhook, start_checkout, subscription_view
from app.services.state import require_user

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/subscription", response_model=SubscriptionPublic)
def subscription(request: Request, user: dict = Depends(get_current_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return subscription_view(db, user["id"])


@router.post("/subscribe", response_model=CheckoutResponse)
async def subscribe(request: Request, user: dict = Depends(get_current_user)) -> dict:
    return await start_checkout(
        store=request.app.state.store,
        settings=request.app.state.settings,
        http=request.app.state.http,
        user_id=user["id"],
    )


@router.post("/webhook", status_code=204)
async def webhook(request: Request) -> Response:
    raw = await request.body()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError(400, "invalid_webhook", "Webhook signature could not be verified") from exc
    if not isinstance(event, dict):
        raise AppError(400, "invalid_webhook", "Webhook signature could not be verified")
    headers = {key.lower(): value for key, value in request.headers.items()}
    await apply_webhook(
        store=request.app.state.store,
        settings=request.app.state.settings,
        http=request.app.state.http,
        headers=headers,
        event=event,
    )
    return Response(status_code=204)
