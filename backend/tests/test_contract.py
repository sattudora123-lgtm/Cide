from fastapi.testclient import TestClient

EXPECTED = {
    "/api/v1/health": ["get"],
    "/api/v1/ready": ["get"],
    "/api/v1/auth/register": ["post"],
    "/api/v1/auth/login": ["post"],
    "/api/v1/auth/refresh": ["post"],
    "/api/v1/auth/logout": ["post"],
    "/api/v1/auth/me": ["get"],
    "/api/v1/billing/subscription": ["get"],
    "/api/v1/billing/subscribe": ["post"],
    "/api/v1/billing/webhook": ["post"],
    "/api/v1/agents": ["get", "post"],
    "/api/v1/agents/{agent_id}": ["get", "patch"],
    "/api/v1/agents/{agent_id}/disable": ["post"],
    "/api/v1/agents/{agent_id}/rotate-token": ["post"],
    "/api/v1/agent-link/heartbeat": ["post"],
    "/api/v1/agent-link/assignments": ["get"],
    "/api/v1/agent-link/events": ["post"],
    "/api/v1/tasks": ["get", "post"],
    "/api/v1/tasks/{task_id}": ["get"],
    "/api/v1/tasks/{task_id}/cancel": ["post"],
    "/api/v1/tasks/{task_id}/plan": ["post"],
    "/api/v1/tasks/{task_id}/workflow": ["post"],
    "/api/v1/tasks/{task_id}/events": ["get"],
    "/api/v1/steps/{step_id}/assign": ["post"],
    "/api/v1/steps/{step_id}/approve": ["post"],
    "/api/v1/steps/{step_id}/deny": ["post"],
    "/api/v1/steps/{step_id}/dispatch": ["post"],
    "/api/v1/providers": ["get", "post"],
    "/api/v1/providers/{provider_id}": ["delete"],
    "/api/v1/browser-jobs": ["get", "post"],
    "/api/v1/browser-jobs/{job_id}": ["get"],
    "/api/v1/browser-jobs/{job_id}/result": ["post"],
}


def test_health_security_headers_and_body_limit(client):
    health = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-request-id"]
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    oversized = client.post(
        "/api/v1/auth/login",
        content=b"{" + b"x" * 5000,
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "payload_too_large"


def test_openapi_contract(app):
    schema = app.openapi()
    operations = {
        path: sorted(method for method in methods if method != "parameters")
        for path, methods in schema["paths"].items()
    }
    assert operations == EXPECTED
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert "Host AI planning" in schema["info"]["description"]


def test_tampered_vault_fails_ready(app):
    target = app.state.store.directory / "users.enc"
    blob = bytearray(target.read_bytes())
    blob[-1] ^= 0x01
    target.write_bytes(blob)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_integrity_error"
