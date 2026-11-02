"""PayPal Subscriptions API. Calls go only to PayPal's official hosts."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.errors import AppError

logger = logging.getLogger("cide.paypal")

_LIVE_API = "https://api-m.paypal.com"
_SANDBOX_API = "https://api-m.sandbox.paypal.com"
_CERT_HOSTS = {"api.paypal.com", "api.sandbox.paypal.com"}
_APPROVAL_HOSTS = {"www.paypal.com", "www.sandbox.paypal.com", "paypal.com", "sandbox.paypal.com"}


class PayPalError(Exception):
    pass


def paypal_api_base(mode: str) -> str:
    if mode == "live":
        return _LIVE_API
    if mode == "sandbox":
        return _SANDBOX_API
    raise PayPalError


def paypal_configured(settings: Settings) -> bool:
    return bool(
        settings.paypal_mode in {"sandbox", "live"}
        and settings.paypal_client_id
        and settings.paypal_client_secret
        and settings.paypal_webhook_id
        and settings.paypal_plan_id
    )


async def create_subscription(
    http: httpx.AsyncClient,
    settings: Settings,
    *,
    user_id: str,
) -> dict:
    token = await _access_token(http, settings)
    response = await _post(
        http,
        f"{paypal_api_base(settings.paypal_mode)}/v1/billing/subscriptions",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "plan_id": settings.paypal_plan_id,
            "custom_id": user_id,
            "application_context": {
                "brand_name": "CIDE",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": settings.paypal_return_url,
                "cancel_url": settings.paypal_cancel_url,
            },
        },
    )
    subscription_id = response.get("id")
    approval_url = _approval_url(response.get("links") or [])
    if not isinstance(subscription_id, str) or not subscription_id or approval_url is None:
        raise PayPalError
    return {"subscription_id": subscription_id, "approval_url": approval_url}


async def verify_webhook(
    http: httpx.AsyncClient,
    settings: Settings,
    *,
    headers: dict[str, str],
    event: dict,
) -> bool:
    cert_url = headers.get("paypal-cert-url", "")
    if not _allowed_cert_url(cert_url):
        return False
    required = ("paypal-auth-algo", "paypal-transmission-id", "paypal-transmission-sig", "paypal-transmission-time")
    if any(not headers.get(name) for name in required):
        return False
    token = await _access_token(http, settings)
    try:
        response = await _post(
            http,
            f"{paypal_api_base(settings.paypal_mode)}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "auth_algo": headers["paypal-auth-algo"],
                "cert_url": cert_url,
                "transmission_id": headers["paypal-transmission-id"],
                "transmission_sig": headers["paypal-transmission-sig"],
                "transmission_time": headers["paypal-transmission-time"],
                "webhook_id": settings.paypal_webhook_id,
                "webhook_event": event,
            },
        )
    except PayPalError:
        return False
    return response.get("verification_status") == "SUCCESS"


async def _access_token(http: httpx.AsyncClient, settings: Settings) -> str:
    response = await _post(
        http,
        f"{paypal_api_base(settings.paypal_mode)}/v1/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        auth=(settings.paypal_client_id, settings.paypal_client_secret),
    )
    token = response.get("access_token")
    if not isinstance(token, str) or not token:
        raise PayPalError
    return token


async def _post(http: httpx.AsyncClient, url: str, **kwargs) -> dict:
    try:
        response = await http.post(url, **kwargs)
    except httpx.HTTPError as exc:
        logger.warning("paypal request failed")
        raise PayPalError from exc
    if response.status_code not in {200, 201}:
        logger.warning("paypal request failed status=%s", response.status_code)
        raise PayPalError
    try:
        payload = response.json()
    except ValueError as exc:
        raise PayPalError from exc
    if not isinstance(payload, dict):
        raise PayPalError
    return payload


def _approval_url(links: list) -> str | None:
    for link in links:
        if not isinstance(link, dict) or link.get("rel") != "approve":
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and host in _APPROVAL_HOSTS and not parsed.username:
            return href
    return None


def _allowed_cert_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in _CERT_HOSTS and not parsed.username
