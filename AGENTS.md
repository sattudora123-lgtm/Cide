# AGENTS.md — CIDE Development Instructions

## 1. Project Identity

Project: CIDE

Description: Multi-AI orchestration application.

Core concept: One Host AI coordinates multiple AI agents and browser-based AI models to complete user tasks.

All AI coding agents must understand that CIDE is an application, NOT an operating system.

## 2. Development Principles

Every coding agent must:

- Understand the existing codebase before modifying it.
- Follow the existing architecture and coding conventions.
- Avoid unnecessary dependencies.
- Write modular and maintainable code.
- Handle errors properly.
- Consider security in every implementation.
- Avoid duplicating existing functionality.
- Never pretend an unimplemented feature exists.
- Never overwrite another developer's work without approval.

## 3. Core System Architecture

The project contains these major systems:

### A. Host AI

Responsible for understanding user requests, breaking tasks into smaller subtasks, planning execution workflows, assigning tasks to agents, monitoring execution, evaluating agent outputs, and producing the final response.

Host planning is owned by SatDev. The backend stores an explicit workflow. It does not invent one.

### B. Agent Manager

Responsible for agent registration, capability discovery, task assignment, execution lifecycle management, agent communication, and status and progress reporting.

### C. AI Integrations

Responsible for connecting supported AI providers, integrating installed coding agents, managing provider-specific communication, and handling failures and timeouts.

### D. Browser AI Connector

Responsible for recording user-authorized prompts for supported AI websites and accepting a result the user submits. It must never bypass authentication, access controls, CAPTCHAs, or website security restrictions, and the backend does not open those sites.

### E. Monitoring Dashboard

The backend exposes task, agent, event, and result reads. The dashboard UI is a separate frontend.

### F. Voice System

Voice is not implemented in this backend. Text task creation is the supported input.

## 4. Team Ownership

SatDev — Project Lead and AI Architect. Owns architecture, Host AI design, orchestration logic, cross-module integration, and technical decisions.

MonkeyGod_666 — Full-Stack Developer and Backend Lead. Owns backend architecture, APIs, storage, authentication, backend infrastructure, and backend integration reviews.

Programmer Also Artist — Backend Developer. Owns assigned backend modules, agent execution services, API integrations, storage operations, and error handling.

Other team members must follow their assigned module ownership. Richer executors plug into `backend/app/services/execution.py` without rewriting the routes.

## 5. Git Collaboration Rules

- Never push directly to main.
- Use feature branches.
- Use dev as the integration branch.
- Submit pull requests before merging.
- Do not force-push shared branches.
- Pull the latest changes before beginning work.
- Avoid editing files owned by other developers without coordination.
- Resolve merge conflicts carefully.
- Never commit secrets, credentials, `.env`, or the `backend/data` directory.

Suggested branch names: `feature/host-ai`, `feature/frontend`, `feature/backend`, `feature/ai-integrations`, `feature/voice`, `fix/bug-description`.

## 6. Security Requirements

Security is mandatory.

- Never expose API keys or credentials.
- Never commit `.env` files.
- Use environment variables for secrets.
- Validate user inputs.
- Apply authentication and authorization.
- Restrict agent permissions.
- Require user approval for sensitive actions.
- Isolate agent execution where appropriate.
- Avoid arbitrary command execution.
- Log important actions without recording secrets.
- Treat AI-generated output and browser content as untrusted input.
- AI agents must never read, print, copy, or expose `.env` contents.
- The JSON data files are encrypted. Do not add a code path that writes plaintext copies.

## 7. Coding Rules

Before modifying code, inspect the relevant files, understand existing dependencies, identify side effects, and check whether another module depends on the code.

When implementing, keep changes focused, follow existing naming conventions, add error handling, add or update tests, and update documentation when the API contract changes.

Do not rewrite entire modules without justification, remove existing functionality without approval, add fake API responses as real integrations, hardcode credentials, or claim tests passed without executing them.

## 8. Testing Requirements

Before submitting changes, run the relevant tests, check broken imports, validate API responses, check error handling, and test integration boundaries. Report untested functionality honestly.

Every pull request should explain what changed, why it changed, which files were modified, which tests were performed, and known limitations.

## 9. Communication Between Agents

When multiple agents work simultaneously, respect module ownership, agree on API contracts before integration, avoid modifying shared files simultaneously, communicate interface changes, do not assume another agent's implementation is complete, and review outputs before integrating them.

## 10. Important Instructions

The repository is the source of truth.

If documentation and actual implementation disagree, inspect the code and report the discrepancy.

Never invent existing functionality.

Never make architectural decisions that conflict with the project's established direction without discussing them with the project lead.

The objective is to build CIDE as a secure, modular, reliable multi-AI orchestration platform.

Build carefully. Integrate properly. Test everything.
