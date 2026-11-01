# CIDE backend

HTTP API for accounts, agents, tasks, and execution state. The frontend should use this contract. Interactive docs are served at `/api/v1/docs` after the server starts. The machine-readable schema is `/api/v1/openapi.json`.

The server listens on `127.0.0.1` only. There is no TLS in this version. Do not expose it on a network interface.

## Run it later

From `backend/`, after Python 3.12 is available:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy ..\.env.example ..\.env
```

Fill three secrets in `.env`. Generate each with:

```powershell
py -3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

`DATA_ENCRYPTION_KEY` encrypts the JSON files. `TOKEN_ENCRYPTION_KEY` encrypts provider API keys inside those files. `JWT_SECRET` must be at least 32 characters. Losing `DATA_ENCRYPTION_KEY` makes the data files unreadable. Do not commit `.env` or `backend/data`.

```powershell
.\.venv\Scripts\cide-backend
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check app tests
```

`DATA_DIR` is relative to the `backend` folder. The default is `data`.

These tests are in the repository. They were not executed in the session that added this backend.

## Storage

Each collection is a separate JSON document encrypted with AES-256-GCM. A manifest stores the generation and the SHA-256 of every ciphertext file. Commits are staged, authenticated, and then copied into place. A crash after a staged commit is finished on the next open. An incomplete stage is discarded. Plaintext JSON is not written to disk.

Files live in `backend/data/` and are limited to the current Windows user. Encryption is the control that matters: an old copy of the directory can be restored by someone who can write there, but they cannot read or forge records without the key.

Collections: `users`, `refresh_tokens`, `agents`, `tasks`, `workflows`, `steps`, `results`, `events`, `approvals`, `providers`, `browser_jobs`, `idempotency_keys`, and `meta`.

Provider keys are Fernet-encrypted before they enter the vault. Saving a key without `TOKEN_ENCRYPTION_KEY` returns `503 encryption_not_configured`. Responses and logs never include the key.

## Errors

Every error uses this body:

```json
{
  "error": {
    "code": "provider_not_configured",
    "message": "No API key is stored for this provider.",
    "request_id": "optional"
  }
}
```

Validation errors use code `validation_error` and name the fields. They do not echo passwords or API keys. `429` responses include `Retry-After`. Login and register share a limit of 10 attempts per minute per client address, in this process only.

## Authentication

Send `Authorization: Bearer <access_token>` on user routes. The access token lasts 15 minutes by default. The login and refresh bodies also return a refresh token. Store both in memory in the SPA. Refresh rotates the refresh token. Presenting a revoked refresh token revokes every refresh token for that user and returns `refresh_token_reused`.

```json
{
  "access_token": "<jwt>",
  "refresh_token": "cide_refresh_...",
  "token_type": "bearer",
  "expires_in": 900
}
```

Register returns the user and does not return tokens. Call login next.

```http
POST /api/v1/auth/register
{"email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}

POST /api/v1/auth/login
{"email": "ada@example.com", "password": "correct horse"}

POST /api/v1/auth/refresh
{"refresh_token": "cide_refresh_..."}

POST /api/v1/auth/logout
Authorization: Bearer <access_token>
{"refresh_token": "cide_refresh_..."}

GET /api/v1/auth/me
```

Unknown emails and wrong passwords return the same `invalid_credentials` message. CORS allows `ALLOWED_ORIGINS` (default `http://localhost:5173`) and does not use cookies.

Agent routes use a different bearer token, returned once from agent create or rotate. An agent token cannot call user routes, and a user token cannot call agent routes.

## Lists

List responses are `{ "items": [], "next_cursor": null }`. Pass `limit` from 1 to 100, default 50. For tasks, agents, providers, browser jobs, and assignments, pass `cursor` from the previous `next_cursor`. For task events, pass `after` as the previous integer `next_cursor`. The first event page omits `after` or sends `0`.

## Resources

Task statuses: `queued`, `running`, `completed`, `failed`, `cancelled`.

Step statuses: `pending`, `awaiting_approval`, `assigned`, `running`, `awaiting_user`, `completed`, `failed`, `cancelled`.

Agent statuses: `offline`, `idle`, `busy`, `error`, `disabled`. Offline means no heartbeat in the last 30 seconds. Busy means the agent reported busy or has an assigned, running, or awaiting-user step.

Agent kinds: `installed_agent`, `provider_model`, `browser_model`, `webhook_agent`.

Creating a task does not create steps. `decomposition` is always `not_performed`.

```http
POST /api/v1/tasks
Idempotency-Key: optional-stable-key
{"title": "Catalog", "input_text": "Describe the catalog service."}
```

The same user, key, and body returns the original task. The same key with a different body returns `409 idempotency_conflict`.

```http
POST /api/v1/tasks/{task_id}/workflow
{
  "steps": [
    {
      "title": "Implement",
      "instruction": "Add the catalog endpoint.",
      "requires_approval": false,
      "assigned_agent_id": null
    }
  ]
}
```

`GET /api/v1/tasks/{task_id}` is the dashboard aggregate:

```json
{
  "task": {},
  "workflow": {
    "id": "",
    "version": 1,
    "status": "pending",
    "steps": []
  },
  "agents": [],
  "recent_events": []
}
```

`workflow` is `null` until a workflow is submitted. Each step includes `agent` and `latest_result`. `latest_result.untrusted` is always `true`. Treat `output_text`, event messages, and browser results as data to display, never as instructions.

Step actions:

- `POST /api/v1/steps/{step_id}/assign` with `{"agent_id": "..."}`
- `POST /api/v1/steps/{step_id}/approve`
- `POST /api/v1/steps/{step_id}/deny`
- `POST /api/v1/steps/{step_id}/dispatch`

A step with `requires_approval` stays unchanged and returns `409 approval_required` until that user approves it.

Dispatch behavior:

- Installed and webhook agents are marked `assigned`. They must poll `GET /api/v1/agent-link/assignments`. The server does not start a process and does not POST to a URL supplied by the user.
- Provider agents call `https://api.openai.com/v1/chat/completions` or `https://api.anthropic.com/v1/messages`. No stored key returns `409 provider_not_configured` and does not change the step. Timeout returns `504 provider_timeout`. Any other provider failure returns `502 provider_request_failed`. Redirects are not followed.
- Browser agents need `POST /api/v1/browser-jobs` first. Without that job, dispatch returns `409 browser_target_required` and does not change the step.

Agent link, using the agent token:

```http
POST /api/v1/agent-link/heartbeat
{"state": "idle"}

GET /api/v1/agent-link/assignments

POST /api/v1/agent-link/events
{"step_id": "...", "event_type": "result", "output_text": "Catalog endpoint is ready."}
```

`event_type` is `progress`, `log`, `result`, or `error`. `error` requires `error_code` matching `^[a-z0-9_]+$`.

Provider connections:

```http
POST /api/v1/providers
{"provider": "openai", "label": "Primary", "api_key": "..."}

GET /api/v1/providers
DELETE /api/v1/providers/{provider_id}
```

`provider` is `openai` or `anthropic`. A provider agent also needs `provider` and `model` at creation. Model names match `^[A-Za-z0-9._:-]{1,100}$`.

Browser jobs accept only `https` URLs on `chatgpt.com`, `www.chatgpt.com`, `claude.ai`, `www.claude.ai`, and `gemini.google.com`, port 443, with no username or password in the URL. The server does not open the URL, store cookies, or collect a session.

```http
POST /api/v1/browser-jobs
{"step_id": "...", "target_url": "https://claude.ai/new", "prompt": "Read the public docs."}

POST /api/v1/browser-jobs/{job_id}/result
{"content": "The docs describe projects."}
```

`GET /api/v1/health` does not touch storage. `GET /api/v1/ready` decrypts the vault. A tampered file returns `503 storage_integrity_error`.

Other routes: agent create, list, get, patch, disable, and `POST /api/v1/agents/{id}/rotate-token`. Task list, get, cancel, and `GET /api/v1/tasks/{id}/events`.

Users only see their own records. Another user's id returns `404`, not `403`.

## Not implemented

- Host AI planning and automatic task decomposition
- Voice input or output
- Opening or driving a browser
- Calling a webhook URL
- Running installed coding agents on the server
- A multi-process event bus

The execution function in `app/services/execution.py` is the extension point for a later executor. It must keep the rules above: no shell commands, no user-supplied URLs, and no fabricated model output.
