import json

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.seed import seed_complimentary_users
from tests.conftest import auth_header

SENOR_PASSWORD = "Senor123456987!"
ARAGON_PASSWORD = "Aragon31612101!"


def _paypal_settings(settings):
    return settings.model_copy(
        update={
            "paypal_mode": "sandbox",
            "paypal_client_id": "paypal-client-id",
            "paypal_client_secret": "paypal-client-secret",
            "paypal_webhook_id": "WH-TEST",
            "paypal_plan_id": "P-TEST",
        }
    )


def _paypal_handler(calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "paypal-access-token", "token_type": "Bearer"})
        if request.url.path.endswith("/v1/billing/subscriptions"):
            return httpx.Response(
                201,
                json={
                    "id": "I-TESTSUB",
                    "status": "APPROVAL_PENDING",
                    "links": [
                        {
                            "rel": "approve",
                            "href": "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=test",
                        }
                    ],
                },
            )
        if request.url.path.endswith("/v1/notifications/verify-webhook-signature"):
            body = json.loads(request.content)
            if body["webhook_event"]["id"] == "bad-signature":
                return httpx.Response(200, json={"verification_status": "FAILURE"})
            return httpx.Response(200, json={"verification_status": "SUCCESS"})
        raise AssertionError(f"unexpected outbound request to {request.url}")

    return handler


def _webhook(client, event_id: str, event_type: str, resource: dict, cert_url: str = "https://api.sandbox.paypal.com/v1/notifications/certs/CERT"):
    return client.post(
        "/api/v1/billing/webhook",
        json={"id": event_id, "event_type": event_type, "resource": resource},
        headers={
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": cert_url,
            "paypal-transmission-id": "transmission-1",
            "paypal-transmission-sig": "signature",
            "paypal-transmission-time": "2026-11-02T00:00:00Z",
        },
    )


def test_complimentary_users_are_hashed_in_the_vault_and_can_log_in(client, app):
    seeded = client.post("/api/v1/auth/login", json={"username": "Senor", "password": SENOR_PASSWORD})
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["subscription"]["complimentary"] is True
    assert seeded.json()["subscription"]["access"] == "allowed"
    headers = {"Authorization": f"Bearer {seeded.json()['access_token']}"}
    assert client.get("/api/v1/tasks", headers=headers).status_code == 200
    aragon = client.post("/api/v1/auth/login", json={"email": "Aragon", "password": ARAGON_PASSWORD})
    assert aragon.status_code == 200
    assert aragon.json()["subscription"]["status"] == "complimentary"
    seed_complimentary_users(app.state.store)
    with app.state.store.transaction() as database:
        usernames = [user.get("username") for user in database["users"]]
        dumped = json.dumps(database)
    assert usernames.count("Senor") == 1
    assert usernames.count("Aragon") == 1
    assert SENOR_PASSWORD not in dumped
    assert ARAGON_PASSWORD not in dumped
    raw = b"".join(path.read_bytes() for path in app.state.store.directory.rglob("*") if path.is_file())
    assert SENOR_PASSWORD.encode() not in raw
    assert ARAGON_PASSWORD.encode() not in raw


def test_trial_allows_access_and_expiry_requires_payment(client, app):
    headers = auth_header(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["subscription"]["status"] == "trial"
    assert me.json()["subscription"]["access"] == "allowed"
    assert client.post("/api/v1/tasks", json={"title": "Notes", "input_text": "Write notes."}, headers=headers).status_code == 201
    with app.state.store.transaction() as database:
        user = next(item for item in database["users"] if item["email"] == "ada@example.com")
        user["trial_ends_at"] = "2000-01-01T00:00:00+00:00"
    blocked = client.get("/api/v1/tasks", headers=headers)
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "subscription_required"
    status = client.get("/api/v1/billing/subscription", headers=headers)
    assert status.status_code == 200
    assert status.json()["access"] == "payment_required"
    checkout = client.post("/api/v1/billing/subscribe", headers=headers)
    assert checkout.status_code == 503
    assert checkout.json()["error"]["code"] == "paypal_not_configured"


def test_paypal_checkout_and_webhook(settings):
    calls: list[str] = []
    application = create_app(_paypal_settings(settings))
    application.state.http_transport = httpx.MockTransport(_paypal_handler(calls))
    with TestClient(application) as client:
        headers = auth_header(client)
        me = client.get("/api/v1/auth/me", headers=headers).json()
        checkout = client.post("/api/v1/billing/subscribe", headers=headers)
        assert checkout.status_code == 200, checkout.text
        assert checkout.json()["subscription_id"] == "I-TESTSUB"
        assert checkout.json()["approval_url"].startswith("https://www.sandbox.paypal.com/")
        assert "/v1/oauth2/token" in calls[0] or calls[0].endswith("/v1/oauth2/token")
        with application.state.store.transaction() as database:
            user = next(item for item in database["users"] if item["id"] == me["id"])
            user["trial_ends_at"] = "2000-01-01T00:00:00+00:00"
        assert client.get("/api/v1/tasks", headers=headers).status_code == 402
        activated = _webhook(
            client,
            "evt-1",
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {"id": "I-TESTSUB", "custom_id": me["id"], "status": "ACTIVE"},
        )
        assert activated.status_code == 204
        assert client.get("/api/v1/tasks", headers=headers).status_code == 200
        rejected = _webhook(
            client,
            "bad-signature",
            "BILLING.SUBSCRIPTION.CANCELLED",
            {"id": "I-TESTSUB", "custom_id": me["id"]},
        )
        assert rejected.status_code == 400
        assert client.get("/api/v1/billing/subscription", headers=headers).json()["status"] == "active"
        before = len(calls)
        evil = _webhook(
            client,
            "evt-2",
            "BILLING.SUBSCRIPTION.CANCELLED",
            {"id": "I-TESTSUB"},
            cert_url="https://evil.example/cert",
        )
        assert evil.status_code == 400
        assert len(calls) == before
