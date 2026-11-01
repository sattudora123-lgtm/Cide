# CIDE

One Host AI. Multiple Agents. One Unified Result.

CIDE is a multi-AI orchestration platform. Users submit a task to the Host AI, which will plan, distribute, monitor, and coordinate work across multiple AI systems. The backend in this repository is the API and encrypted storage that a frontend can connect to later.

CIDE is an application, not an operating system.

## How it works

1. User input — submit a task as text. Voice is not implemented yet.
2. Host AI — planning is a separate module. This backend stores the request and does not invent a workflow.
3. Task distribution — an explicit workflow assigns steps to registered agents.
4. Parallel execution — installed agents poll for work. Configured provider models can be called directly.
5. Progress monitoring — task, step, agent, and event reads feed the future dashboard.
6. Evaluation — the Host AI can read stored results later. Results are marked untrusted.
7. Final result — combining outputs is the Host's job, not this API.

## What is implemented

The backend provides:

- Account registration, login, refresh-token rotation, and logout
- Agent registration, one-time agent tokens, heartbeats, and assignment polling
- Tasks, explicit workflows, approvals, dispatch, and an event feed
- Encrypted local JSON storage
- OpenAI and Anthropic calls only when that user has stored a key
- Browser jobs that record an allowlisted URL and a user-submitted result

Host planning, voice, and live browser automation are not implemented. `POST /api/v1/tasks/{id}/plan` returns `501` with code `host_planner_not_configured`.

## Layout

- `backend/` — FastAPI service. Read `backend/README.md` before building the frontend.
- `AGENTS.md` — team and coding rules.
- `.env.example` — secret names. Copy to `.env` locally. Never commit `.env`.

## Team

| Member | Responsibility |
| --- | --- |
| SatDev | Project Lead and AI Architecture |
| MonkeyGod_666 | Full-Stack Developer and Backend Lead |
| Programmer Also Artist | Backend Developer |
| Member 4 | To be assigned |
| Member 5 | To be assigned |

## Collaboration

Work on a feature branch. Do not push directly to `main`. Use `dev` as the integration branch. Open a pull request, and do not commit API keys, credentials, `.env`, or `backend/data`.
