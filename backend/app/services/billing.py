import logging

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.paypal import PayPalError, create_subscription, paypal_configured, verify_webhook
from app.services.clock import utc_now
from app.services.entitlement import present_subscription
from app.services.state import require_user
from app.storage.vault import EncryptedJsonStore

logger = logging.getLogger("cide.paypal")

_STATUS_BY_EVENT = {
    "BILLING.SUBSCRIPTION.ACTIVATED": "active",
    "BILLING.SUBSCRIPTION.RE-ACTIVATED": "active",
    "BILLING.SUBSCRIPTION.CANCELLED": "cancelled",
    "BILLING.SUBSCRIPTION.EXPIRED": "expired",
    "BILLING.SUBSCRIPTION.SUSPENDED": "suspended",
    "PAYMENT.SALE.COMPLETED": "active",
}


async def start_checkout(
    *,
    store: EncryptedJsonStore,
    settings: Settings,
    http: httpx.AsyncClient,
    user_id: str,
) -> dict:
    if not paypal_configured(settings):
        raise AppError(503, "paypal_not_configured", "PayPal subscription is not configured")
    with store.transaction() as db:
        user = require_user(db, user_id)
        if user.get("complimentary"):
            raise AppError(409, "already_entitled", "This account already has free access")
        if user.get("subscription_status") == "active":
            raise AppError(409, "already_subscribed", "This account already has an active subscription")
    try:
        created = await create_subscription(http, settings, user_id=user_id)
    except PayPalError:
        raise AppError(502, "paypal_request_failed", "PayPal could not start the subscription") from None
    with store.transaction() as db:
        user = require_user(db, user_id)
        if not user.get("complimentary"):
            user["paypal_subscription_id"] = created["subscription_id"]
            user["subscription_status"] = "approval_pending"
            user["updated_at"] = utc_now()
    return {
        "subscription_id": created["subscription_id"],
        "status": "approval_pending",
        "approval_url": created["approval_url"],
    }


def subscription_view(db: dict, user_id: str) -> dict:
    return present_subscription(require_user(db, user_id))


async def apply_webhook(
    *,
    store: EncryptedJsonStore,
    settings: Settings,
    http: httpx.AsyncClient,
    headers: dict[str, str],
    event: dict,
) -> None:
    if not paypal_configured(settings):
        raise AppError(503, "paypal_not_configured", "PayPal webhook is not configured")
    try:
        verified = await verify_webhook(http, settings, headers=headers, event=event)
    except PayPalError:
        verified = False
    if not verified:
        raise AppError(400, "invalid_webhook", "Webhook signature could not be verified")
    event_type = event.get("event_type")
    if not isinstance(event_type, str):
        return
    status = _STATUS_BY_EVENT.get(event_type)
    if status is None:
        logger.info("paypal webhook ignored type=%s", event_type)
        return
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    subscription_id = resource.get("id") if event_type.startswith("BILLING.SUBSCRIPTION.") else resource.get("billing_agreement_id")
    custom_id = resource.get("custom_id") if isinstance(resource.get("custom_id"), str) else None
    if not isinstance(subscription_id, str):
        subscription_id = None
    with store.transaction() as db:
        user = _find_subscriber(db, subscription_id=subscription_id, custom_id=custom_id)
        if user is None or user.get("complimentary"):
            logger.info("paypal webhook ignored type=%s", event_type)
            return
        if subscription_id:
            user["paypal_subscription_id"] = subscription_id
        user["subscription_status"] = status
        user["updated_at"] = utc_now()
    logger.info("paypal webhook applied type=%s", event_type)


def _find_subscriber(db: dict, *, subscription_id: str | None, custom_id: str | None) -> dict | None:
    for user in db["users"]:
        if subscription_id and user.get("paypal_subscription_id") == subscription_id:
            return user
        if custom_id and user["id"] == custom_id:
            return user
    return None
