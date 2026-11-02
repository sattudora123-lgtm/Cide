import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations.chat import ANTHROPIC_URL, APINEX_URL, BYTEZ_URL, GEMINI_URL
from app.main import create_app
from app.services.browser_jobs import validate_target_url
from app.core.errors import AppError
from tests.conftest import auth_header, reject_outbound


API_KEY = "sk-test-key-not-real-9f3a"


def _provider_app(settings, handler):
    application = create_app(settings)
    application.state.http_transport = httpx.MockTransport(handler)
    return application


def _ready_provider_step(client, headers, *, provider="apinex", model="demo-model"):
    agent = client.post(
        "/api/v1/agents",
        json={"name": "Model", "kind": "provider_model", "provider": provider, "model": model},
        headers=headers,
    )
    assert agent.status_code == 201, agent.text
    task = client.post(
        "/api/v1/tasks",
        json={"title": "Summarize", "input_text": "Summarize the notes."},
        headers=headers,
    )
    workflow = client.post(
        f"/api/v1/tasks/{task.json()['id']}/workflow",
        json={
            "steps": [
                {
                    "title": "Summarize",
                    "instruction": "Summarize the notes in one paragraph.",
                    "assigned_agent_id": agent.json()["agent"]["id"],
                }
            ]
        },
        headers=headers,
    )
    assert workflow.status_code == 201, workflow.text
    return task.json()["id"], workflow.json()["steps"][0]["id"]


def test_missing_provider_key_does_not_change_the_step_or_call_out(client):
    headers = auth_header(client)
    task_id, step_id = _ready_provider_step(client, headers)
    response = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "provider_not_configured"
    detail = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()
    assert detail["workflow"]["steps"][0]["status"] == "pending"
    assert detail["workflow"]["steps"][0]["latest_result"] is None
    assert detail["task"]["status"] == "queued"


def test_provider_success_timeout_and_redirect_are_real_outcomes(settings):
    calls = []

    def succeed(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        return httpx.Response(200, json={"choices": [{"message": {"content": "model output"}}]})

    application = _provider_app(settings, succeed)
    with TestClient(application) as client:
        headers = auth_header(client)
        saved = client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Primary", "api_key": API_KEY},
            headers=headers,
        )
        assert saved.status_code == 201, saved.text
        assert API_KEY not in saved.text
        listed = client.get("/api/v1/providers", headers=headers)
        assert API_KEY not in listed.text
        with application.state.store.transaction() as database:
            dumped = json.dumps(database)
        assert API_KEY not in dumped
        raw = b"".join(path.read_bytes() for path in application.state.store.directory.rglob("*") if path.is_file())
        assert API_KEY.encode() not in raw

        task_id, step_id = _ready_provider_step(client, headers)
        dispatched = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert dispatched.status_code == 200, dispatched.text
        assert calls == [APINEX_URL]
        result = dispatched.json()["latest_result"]
        assert result["output_text"] == "model output"
        assert result["untrusted"] is True
        assert client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["task"]["status"] == "completed"

    def time_out(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    timed = settings.model_copy(update={"data_dir": settings.resolved_data_dir().parent / "timeout-vault"})
    timeout_app = _provider_app(timed, time_out)
    with TestClient(timeout_app) as client:
        headers = auth_header(client, email="grace@example.com", name="Grace")
        assert (
            client.post(
                "/api/v1/providers",
                json={"provider": "apinex", "label": "Primary", "api_key": API_KEY},
                headers=headers,
            ).status_code
            == 201
        )
        _task_id, step_id = _ready_provider_step(client, headers)
        response = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "provider_timeout"
        detail = client.get(f"/api/v1/tasks/{_task_id}", headers=headers).json()
        assert detail["workflow"]["steps"][0]["status"] == "failed"
        assert detail["workflow"]["steps"][0]["latest_result"]["error_code"] == "provider_timeout"

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    redirected = settings.model_copy(update={"data_dir": settings.resolved_data_dir().parent / "redirect-vault"})
    redirect_app = _provider_app(redirected, redirect)
    with TestClient(redirect_app) as client:
        headers = auth_header(client, email="lin@example.com", name="Lin")
        client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Primary", "api_key": API_KEY},
            headers=headers,
        )
        _task_id, step_id = _ready_provider_step(client, headers)
        before = len(calls)
        response = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert response.status_code == 502
        assert calls[before:] == [APINEX_URL]


def test_optional_provider_runs_only_after_apinex_fails_and_is_not_user_choice(settings):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == APINEX_URL:
            return httpx.Response(500, json={"error": "down"})
        assert str(request.url) == ANTHROPIC_URL
        assert request.headers["x-api-key"] == "server-anthropic-key"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "fallback output"}]})

    configured = settings.model_copy(
        update={"anthropic_api_key": "server-anthropic-key", "anthropic_model": "claude-test"}
    )
    application = _provider_app(configured, handler)
    with TestClient(application) as client:
        headers = auth_header(client)
        for rejected in ("openai", "anthropic", "gemini"):
            response = client.post(
                "/api/v1/providers",
                json={"provider": rejected, "label": "Hidden", "api_key": API_KEY},
                headers=headers,
            )
            assert response.status_code == 422
        client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Apinex", "api_key": API_KEY},
            headers=headers,
        )
        _task_id, step_id = _ready_provider_step(client, headers, provider="apinex", model="demo-model")
        dispatched = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert dispatched.status_code == 200, dispatched.text
        assert dispatched.json()["latest_result"]["output_text"] == "fallback output"
        assert calls == [APINEX_URL, ANTHROPIC_URL]


def test_browser_job_never_calls_out_and_rejects_other_urls(client):
    headers = auth_header(client)
    agent = client.post(
        "/api/v1/agents",
        json={"name": "Browser", "kind": "browser_model"},
        headers=headers,
    )
    task = client.post("/api/v1/tasks", json={"title": "Research", "input_text": "Check the docs."}, headers=headers)
    workflow = client.post(
        f"/api/v1/tasks/{task.json()['id']}/workflow",
        json={
            "steps": [
                {
                    "title": "Read",
                    "instruction": "Read the public docs.",
                    "assigned_agent_id": agent.json()["agent"]["id"],
                }
            ]
        },
        headers=headers,
    )
    step_id = workflow.json()["steps"][0]["id"]
    early = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "browser_target_required"
    created = client.post(
        "/api/v1/browser-jobs",
        json={"step_id": step_id, "target_url": "https://claude.ai/new", "prompt": "Read the public docs."},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "awaiting_user"
    assert created.json()["untrusted"] is True
    detail = client.get(f"/api/v1/tasks/{task.json()['id']}", headers=headers).json()
    assert detail["workflow"]["steps"][0]["status"] == "awaiting_user"
    again = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
    assert again.status_code == 200
    submitted = client.post(
        f"/api/v1/browser-jobs/{created.json()['id']}/result",
        json={"content": "The docs describe projects."},
        headers=headers,
    )
    assert submitted.status_code == 200
    finished = client.get(f"/api/v1/tasks/{task.json()['id']}", headers=headers).json()
    assert finished["workflow"]["steps"][0]["latest_result"]["untrusted"] is True
    assert finished["workflow"]["steps"][0]["latest_result"]["output_text"] == "The docs describe projects."

    rejected = client.post(
        "/api/v1/browser-jobs",
        json={"step_id": step_id, "target_url": "https://evil.example/prompt", "prompt": "nope"},
        headers=headers,
    )
    assert rejected.status_code == 422
    for url in ("http://chatgpt.com", "https://user:pass@chatgpt.com", "https://127.0.0.1/latest"):
        with pytest.raises(AppError):
            validate_target_url(url)
    assert validate_target_url("https://gemini.google.com/app") == "https://gemini.google.com/app"


def test_webhook_dispatch_does_not_call_a_url(client):
    headers = auth_header(client)
    agent = client.post(
        "/api/v1/agents",
        json={"name": "Hook", "kind": "webhook_agent"},
        headers=headers,
    )
    task = client.post("/api/v1/tasks", json={"title": "Ping", "input_text": "Ping the agent."}, headers=headers)
    workflow = client.post(
        f"/api/v1/tasks/{task.json()['id']}/workflow",
        json={
            "steps": [
                {
                    "title": "Ping",
                    "instruction": "Wait for the poll.",
                    "assigned_agent_id": agent.json()["agent"]["id"],
                }
            ]
        },
        headers=headers,
    )
    step_id = workflow.json()["steps"][0]["id"]
    response = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"


def test_apinex_and_bytez_use_their_official_urls(settings):
    def succeed(request: httpx.Request) -> httpx.Response:
        if str(request.url) == APINEX_URL:
            assert request.headers["authorization"] == f"Bearer {API_KEY}"
            return httpx.Response(200, json={"choices": [{"message": {"content": "apinex output"}}]})
        assert str(request.url) == f"{BYTEZ_URL}Qwen/Qwen2.5-7B-Instruct"
        assert request.headers["authorization"] == API_KEY
        return httpx.Response(200, json={"error": None, "output": "bytez output"})

    application = _provider_app(settings, succeed)
    with TestClient(application) as client:
        headers = auth_header(client)
        for provider in ("apinex", "bytez"):
            assert (
                client.post(
                    "/api/v1/providers",
                    json={"provider": provider, "label": provider, "api_key": API_KEY},
                    headers=headers,
                ).status_code
                == 201
            )
        _task_id, step_id = _ready_provider_step(client, headers, provider="apinex", model="claude-sonnet-5.5")
        apinex = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert apinex.status_code == 200, apinex.text
        assert apinex.json()["latest_result"]["output_text"] == "apinex output"
        _task_id, step_id = _ready_provider_step(
            client,
            headers,
            provider="bytez",
            model="Qwen/Qwen2.5-7B-Instruct",
        )
        bytez = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert bytez.status_code == 200, bytez.text
        assert bytez.json()["latest_result"]["output_text"] == "bytez output"


def test_gemini_is_not_called_when_apinex_succeeds(settings):
    calls: list[str] = []

    def succeed(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "apinex output"}}]})

    configured = settings.model_copy(
        update={"gemini_api_key": "server-gemini-key", "gemini_model": "gemini-2.5-flash"}
    )
    application = _provider_app(configured, succeed)
    with TestClient(application) as client:
        headers = auth_header(client, email="mina@example.com", name="Mina")
        client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Apinex", "api_key": API_KEY},
            headers=headers,
        )
        _task_id, step_id = _ready_provider_step(client, headers)
        response = client.post(f"/api/v1/steps/{step_id}/dispatch", headers=headers)
        assert response.status_code == 200, response.text
        assert calls == [APINEX_URL]
        assert GEMINI_URL not in "".join(calls)


def test_provider_calls_are_rate_limited(settings):
    def succeed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    limited = settings.model_copy(
        update={"provider_rate_limit": 1, "data_dir": settings.resolved_data_dir().parent / "rate-vault"}
    )
    application = _provider_app(limited, succeed)
    with TestClient(application) as client:
        headers = auth_header(client, email="rio@example.com", name="Rio")
        client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Apinex", "api_key": API_KEY},
            headers=headers,
        )
        _task_id, first_step = _ready_provider_step(client, headers, provider="apinex", model="gpt-6.1-sol")
        assert client.post(f"/api/v1/steps/{first_step}/dispatch", headers=headers).status_code == 200
        _task_id, second_step = _ready_provider_step(client, headers, provider="apinex", model="gpt-6.1-sol")
        blocked = client.post(f"/api/v1/steps/{second_step}/dispatch", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "provider_rate_limited"
        assert blocked.headers["retry-after"] == "60"
        detail = client.get(f"/api/v1/tasks/{_task_id}", headers=headers).json()
        assert detail["workflow"]["steps"][0]["status"] == "pending"


def test_encryption_key_is_required_before_a_provider_key_is_stored(settings):
    bare = settings.model_copy(update={"token_encryption_key": ""})
    application = create_app(bare)
    application.state.http_transport = httpx.MockTransport(reject_outbound)
    with TestClient(application) as client:
        headers = auth_header(client)
        response = client.post(
            "/api/v1/providers",
            json={"provider": "apinex", "label": "Primary", "api_key": API_KEY},
            headers=headers,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "encryption_not_configured"
        assert client.get("/api/v1/providers", headers=headers).json()["items"] == []
