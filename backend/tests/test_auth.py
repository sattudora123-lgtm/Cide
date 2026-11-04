import base64
import os

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import auth_header, login, register


def test_register_login_me_and_duplicate_email(client):
    created = register(client)
    assert created["email"] == "ada@example.com"
    assert "password" not in created
    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "Ada@example.com", "password": "correct horse", "display_name": "Ada"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_taken"
    tokens = login(client)
    assert tokens["token_type"] == "bearer"
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == created["id"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_hides_which_field_was_wrong(client):
    register(client)
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "correct horse"},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "incorrect-password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_refresh_rotation_reuse_and_logout(client):
    register(client)
    first = login(client)
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200
    second = refreshed.json()["refresh_token"]
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "refresh_token_reused"
    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert revoked.status_code == 401

    tokens = login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    logout = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers)
    assert logout.status_code == 204
    assert logout.content == b""
    after = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers)
    assert after.status_code == 401


def test_validation_does_not_echo_the_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": "short", "display_name": "Ada"},
    )
    assert response.status_code == 422
    assert "short" not in response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_rate_limit(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    limited = settings.model_copy(update={"login_rate_limit": 2})
    application = create_app(limited)
    with TestClient(application) as client:
        body = {"email": "ada@example.com", "password": "incorrect-password"}
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
        blocked = client.post("/api/v1/auth/login", json=body)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert blocked.headers["retry-after"] == "60"


def test_settings_reject_a_short_jwt_secret_without_echoing_it():
    secret = "too-short-but-unique"
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            jwt_secret=secret,
            data_encryption_key=base64.urlsafe_b64encode(os.urandom(32)).decode(),
            token_encryption_key=Fernet.generate_key().decode(),
        )
    assert secret not in str(caught.value)


def test_auth_header_helper_can_call_me(client):
    headers = auth_header(client)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
