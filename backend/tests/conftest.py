import base64
import os

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def reject_outbound(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected outbound request to {request.url}")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        app_env="test",
        data_dir=tmp_path / "vault",
        data_encryption_key=base64.urlsafe_b64encode(os.urandom(32)).decode(),
        token_encryption_key=Fernet.generate_key().decode(),
        jwt_secret="test-jwt-secret-must-be-32-characters",
        allowed_origins="http://localhost:5173",
        provider_timeout_seconds=2,
        provider_max_tokens=64,
        heartbeat_stale_seconds=30,
        login_rate_limit=10,
        login_rate_window_seconds=60,
        max_body_bytes=4096,
    )


@pytest.fixture
def app(settings):
    application = create_app(settings)
    application.state.http_transport = httpx.MockTransport(reject_outbound)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def register(client, email="ada@example.com", password="correct horse", name="Ada"):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email="ada@example.com", password="correct horse"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(client, email="ada@example.com", password="correct horse", name="Ada"):
    register(client, email=email, password=password, name=name)
    token = login(client, email=email, password=password)["access_token"]
    return {"Authorization": f"Bearer {token}"}
