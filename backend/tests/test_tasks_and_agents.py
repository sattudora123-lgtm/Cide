from tests.conftest import auth_header


def _agent(client, headers, **overrides):
    body = {"name": "Coder", "kind": "installed_agent", "capabilities": ["backend"]}
    body.update(overrides)
    response = client.post("/api/v1/agents", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _task(client, headers, title="Build the catalog"):
    response = client.post(
        "/api/v1/tasks",
        json={"title": title, "input_text": "Describe the catalog service."},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_task_create_does_not_invent_a_workflow_and_plan_is_not_implemented(client):
    headers = auth_header(client)
    created = _task(client, headers)
    assert created["status"] == "queued"
    assert created["decomposition"] == "not_performed"
    detail = client.get(f"/api/v1/tasks/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["workflow"] is None
    plan = client.post(f"/api/v1/tasks/{created['id']}/plan", headers=headers)
    assert plan.status_code == 501
    assert plan.json()["error"]["code"] == "host_planner_not_configured"
    assert client.get(f"/api/v1/tasks/{created['id']}", headers=headers).json()["workflow"] is None


def test_users_are_isolated(client):
    ada = auth_header(client, email="ada@example.com", name="Ada")
    grace = auth_header(client, email="grace@example.com", name="Grace")
    task = _task(client, ada)
    missing = client.get(f"/api/v1/tasks/{task['id']}", headers=grace)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"


def test_idempotency_key(client):
    headers = auth_header(client)
    key = {"Idempotency-Key": "task-create-1"}
    body = {"title": "Catalog", "input_text": "Write the catalog."}
    first = client.post("/api/v1/tasks", json=body, headers={**headers, **key})
    second = client.post("/api/v1/tasks", json=body, headers={**headers, **key})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    conflict = client.post(
        "/api/v1/tasks",
        json={"title": "Different", "input_text": "Write the catalog."},
        headers={**headers, **key},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_agent_token_scope_heartbeat_and_approval_gate(client, app):
    headers = auth_header(client)
    created = _agent(client, headers)
    agent_token = created["token"]
    agent_id = created["agent"]["id"]
    assert "token_hash" not in created["agent"]
    assert created["agent"]["status"] == "offline"
    user_on_link = client.post("/api/v1/agent-link/heartbeat", headers=headers)
    assert user_on_link.status_code == 401
    agent_on_user = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {agent_token}"})
    assert agent_on_user.status_code == 401

    beat = client.post(
        "/api/v1/agent-link/heartbeat",
        json={"state": "idle"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert beat.status_code == 200
    assert beat.json()["status"] == "idle"
    rotated = client.post(f"/api/v1/agents/{agent_id}/rotate-token", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["token"] != agent_token
    old_token = client.post(
        "/api/v1/agent-link/heartbeat",
        json={"state": "idle"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert old_token.status_code == 401
    agent_token = rotated.json()["token"]
    listed = client.get("/api/v1/agents", headers=headers)
    assert listed.json()["items"][0]["status"] == "idle"

    task = _task(client, headers)
    workflow = client.post(
        f"/api/v1/tasks/{task['id']}/workflow",
        json={
            "steps": [
                {
                    "title": "Implement",
                    "instruction": "Add the catalog endpoint.",
                    "requires_approval": True,
                    "assigned_agent_id": agent_id,
                }
            ]
        },
        headers=headers,
    )
    assert workflow.status_code == 201, workflow.text
    step = workflow.json()["steps"][0]
    assert step["status"] == "awaiting_approval"
    blocked = client.post(f"/api/v1/steps/{step['id']}/dispatch", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "approval_required"
    still = client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()
    assert still["workflow"]["steps"][0]["status"] == "awaiting_approval"
    assert still["task"]["status"] == "queued"

    approved = client.post(f"/api/v1/steps/{step['id']}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "pending"
    dispatched = client.post(f"/api/v1/steps/{step['id']}/dispatch", headers=headers)
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["status"] == "assigned"
    assignments = client.get("/api/v1/agent-link/assignments", headers={"Authorization": f"Bearer {agent_token}"})
    assert assignments.status_code == 200
    assert assignments.json()["items"][0]["step_id"] == step["id"]

    progress = client.post(
        "/api/v1/agent-link/events",
        json={"step_id": step["id"], "event_type": "progress", "message": "Writing the handler"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert progress.status_code == 200
    note = client.post(
        "/api/v1/agent-link/events",
        json={"step_id": step["id"], "event_type": "log", "message": "Handler compiles"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert note.status_code == 200
    result = client.post(
        "/api/v1/agent-link/events",
        json={"step_id": step["id"], "event_type": "result", "output_text": "Catalog endpoint is ready."},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert result.json()["status"] == "completed"
    detail = client.get(f"/api/v1/tasks/{task['id']}", headers=headers).json()
    assert detail["task"]["status"] == "completed"
    assert detail["workflow"]["steps"][0]["latest_result"]["untrusted"] is True
    assert detail["workflow"]["steps"][0]["latest_result"]["output_text"] == "Catalog endpoint is ready."

    first_page = client.get(f"/api/v1/tasks/{task['id']}/events", params={"limit": 2}, headers=headers)
    assert first_page.status_code == 200
    body = first_page.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] == body["items"][-1]["seq"]
    second_page = client.get(
        f"/api/v1/tasks/{task['id']}/events",
        params={"after": body["next_cursor"], "limit": 2},
        headers=headers,
    )
    assert second_page.json()["next_cursor"] is None
    seen = [item["seq"] for item in body["items"] + second_page.json()["items"]]
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen))

    with app.state.store.transaction() as database:
        database["agents"][0]["last_heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    stale = client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert stale.json()["status"] == "offline"

    raw = b"".join(path.read_bytes() for path in app.state.store.directory.rglob("*") if path.is_file())
    assert b"ada@example.com" not in raw
    assert b"correct horse" not in raw
    assert b"Catalog endpoint is ready." not in raw
