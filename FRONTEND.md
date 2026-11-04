# Frontend guide for CIDE

This is the list of what the frontend has to contain. The backend is already the API. The UI does not plan tasks, does not run agents, and does not choose GPT, Claude, or Gemini.

Base URL during local development: `http://127.0.0.1:8000`

The frontend origin must be `http://localhost:5173`, or whatever is set in `ALLOWED_ORIGINS`. Send `Authorization: Bearer <access_token>` on every route except health, ready, register, login, refresh, and the PayPal webhook. Do not use cookies.

Every error looks like this:

```json
{ "error": { "code": "subscription_required", "message": "…", "request_id": "…" } }
```

Show `message` to the user. Branch on `code`. Agent and browser text is untrusted: display it as plain text, never as HTML and never as a command.

## 1. Register and log in

Screens:

- Register: email, password (10 to 128 characters), display name
- Log in: email or username, plus password
- Session refresh when an API call returns `401 invalid_access_token`

```http
POST /api/v1/auth/register
{"email": "ada@example.com", "password": "correct horse", "display_name": "Ada"}

POST /api/v1/auth/login
{"email": "ada@example.com", "password": "correct horse"}

POST /api/v1/auth/login
{"username": "Senor", "password": "…"}

POST /api/v1/auth/refresh
{"refresh_token": "cide_refresh_…"}

POST /api/v1/auth/logout
{"refresh_token": "cide_refresh_…"}

GET /api/v1/auth/me
```

Register returns the user and no tokens. Call login next. Keep the access token and refresh token in memory. Login and refresh also return `subscription`.

`Senor` and `Aragon` are built-in accounts. They always have access. Give them a normal login form; do not build a separate admin screen for them.

A new account has `subscription.status` of `trial` and `subscription.access` of `allowed` for 7 days. When access is `payment_required`, product screens must stop and the billing screen must open. Those product calls return `402` with code `subscription_required`.

## 2. Billing

Screen contents:

- Current status, trial end time, and whether access is allowed
- A subscribe button
- After subscribe, send the browser to `approval_url`

```http
GET /api/v1/billing/subscription

POST /api/v1/billing/subscribe
```

Subscribe returns:

```json
{"subscription_id": "I-…", "status": "approval_pending", "approval_url": "https://www.sandbox.paypal.com/…"}
```

The PayPal webhook is server-only. Do not call `POST /api/v1/billing/webhook` from the frontend. After the user comes back from PayPal, call `GET /api/v1/billing/subscription` again. `status: active` means they can use the product. `503 paypal_not_configured` means the server owner has not filled in the PayPal environment variables.

## 3. Provider keys

This screen has two key forms and nothing else:

- Apinex key, saved as provider `apinex`
- Bytez key, saved as provider `bytez`

```http
POST /api/v1/providers
{"provider": "apinex", "label": "Apinex", "api_key": "…"}

POST /api/v1/providers
{"provider": "bytez", "label": "Bytez", "api_key": "…"}

GET /api/v1/providers
DELETE /api/v1/providers/{provider_id}
```

The list never includes the key. Do not add inputs, toggles, or menus for GPT, Claude, Gemini, OpenAI, or Anthropic. The server uses those only when the operator put a key in the server environment and both Apinex and Bytez failed to return a result. The user does not choose that.

## 4. Agents

Screen contents:

- Create, list, edit, disable, and rotate token
- Kind is one of `installed_agent`, `provider_model`, `browser_model`, `webhook_agent`
- For `provider_model`, the optional fields are `provider` (`apinex` or `bytez`) and `model`. That only decides which of those two is tried first. It is not a general model picker.

```http
POST /api/v1/agents
{"name": "Writer", "kind": "provider_model", "provider": "apinex", "model": "demo-model", "capabilities": ["writing"]}
```

The create response includes `token` once. Show it once and store it for the installed-agent screen. Rotate replaces it:

```http
POST /api/v1/agents/{agent_id}/rotate-token
```

Agent `status` is `offline`, `idle`, `busy`, `error`, or `disabled`. Offline means no heartbeat for 30 seconds.

Installed-agent screen, using the agent token rather than the user token:

```http
POST /api/v1/agent-link/heartbeat
{"state": "idle"}

GET /api/v1/agent-link/assignments

POST /api/v1/agent-link/events
{"step_id": "…", "event_type": "result", "output_text": "…"}
```

`event_type` is `progress`, `log`, `result`, or `error`. An error also needs `error_code` made of lowercase letters, numbers, and underscores.

## 5. Tasks and the dashboard

This is the main screen. One task view calls:

```http
GET /api/v1/tasks/{task_id}
```

Show `task`, and when `workflow` is not null show its steps. Each step shows title, instruction, status, the assigned agent, and `latest_result`. `latest_result.untrusted` is always true.

Create does not create steps. There is no planner screen. `POST /api/v1/tasks/{id}/plan` returns `501 host_planner_not_configured`. The user, or a later Host module, submits the steps:

```http
POST /api/v1/tasks
{"title": "Catalog", "input_text": "Describe the catalog service."}

POST /api/v1/tasks/{task_id}/workflow
{"steps": [{"title": "Write", "instruction": "Write the description.", "requires_approval": false, "assigned_agent_id": null}]}
```

Step actions:

```http
POST /api/v1/steps/{step_id}/assign
{"agent_id": "…"}

POST /api/v1/steps/{step_id}/approve
POST /api/v1/steps/{step_id}/deny
POST /api/v1/steps/{step_id}/dispatch
```

If `requires_approval` is true, dispatch returns `409 approval_required` until that user approves. Dispatch then asks the server to run the step. The UI does not call Apinex, Bytez, or any other model host itself.

Poll progress with:

```http
GET /api/v1/tasks/{task_id}/events?after=0&limit=50
```

Pass the returned `next_cursor` as the next `after`. Lists of tasks and agents use `cursor` and `limit` the same way, and the body is `{ "items": [], "next_cursor": null }`.

Task status is `queued`, `running`, `completed`, `failed`, or `cancelled`. Step status is `pending`, `awaiting_approval`, `assigned`, `running`, `awaiting_user`, `completed`, `failed`, or `cancelled`.

`429 provider_rate_limited` means the server is waiting before it calls a provider again. Show the message and leave the step as it was. `409 provider_not_configured` means neither Apinex nor Bytez has a saved key and no server fallback is available.

## 6. Optional browser handoff

This screen is optional. It does not automate a website. The user picks an allowlisted page, then pastes the answer back.

Allowed sites: `https://chatgpt.com`, `https://www.chatgpt.com`, `https://claude.ai`, `https://www.claude.ai`, and `https://gemini.google.com`.

```http
POST /api/v1/browser-jobs
{"step_id": "…", "target_url": "https://claude.ai/new", "prompt": "Read the public docs."}

POST /api/v1/browser-jobs/{job_id}/result
{"content": "The docs describe projects."}
```

Open `target_url` in the user's browser. Do not collect cookies or sessions.

## Do not build

- A selector for GPT, Claude, Gemini, OpenAI, or Anthropic
- A Host AI planner
- Voice input or output
- A button that runs shell commands or calls provider URLs from the browser
- A PayPal webhook caller
