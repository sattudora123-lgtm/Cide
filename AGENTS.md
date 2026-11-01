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

The project is expected to contain these major systems:

### A. Host AI
Responsible for:
- Understanding user requests.
- Breaking tasks into smaller subtasks.
- Planning execution workflows.
- Assigning tasks to agents.
- Monitoring execution.
- Evaluating agent outputs.
- Producing the final response.

### B. Agent Manager
Responsible for:
- Agent registration.
- Agent capability discovery.
- Task assignment.
- Execution lifecycle management.
- Agent communication.
- Status and progress reporting.

### C. AI Integrations
Responsible for:
- Connecting supported AI providers.
- Integrating installed coding agents.
- Managing provider-specific communication.
- Handling failures and timeouts.
- Supporting browser-based AI interactions.

### D. Browser AI Connector
Responsible for:
- Opening supported AI websites in the user's browser.
- Managing browser sessions safely.
- Sending user-authorized prompts.
- Collecting responses where technically supported.
- Handling authentication and session errors.

Never attempt to bypass authentication, access controls, CAPTCHAs or website security restrictions.

### E. Monitoring Dashboard
Responsible for:
- Agent status.
- Task progress.
- Execution history.
- Individual agent results.
- Errors and warnings.
- Overall workflow visibility.

### F. Voice System
Responsible for:
- Voice-to-text.
- Text-to-voice.
- Microphone permissions.
- Voice interaction with the Host AI.

## 4. Team Ownership

### SatDev — Project Lead & AI Architect
Primary ownership:
- Overall architecture.
- Host AI design.
- Orchestration logic.
- Cross-module integration.
- Technical decisions.

### MonkeyGod_666 — Full-Stack Developer & Backend Lead
Primary ownership:
- Backend architecture.
- APIs.
- Database.
- Authentication.
- Backend infrastructure.
- Backend integration reviews.

### Programmer Also Artist — Backend Developer
Primary ownership:
- Assigned backend modules.
- Agent execution services.
- API integrations.
- Database operations.
- Error handling and logging.

Other team members must follow their assigned module ownership.

## 5. Git Collaboration Rules

- Never push directly to `main`.
- Use feature branches.
- Use `dev` as the integration branch.
- Submit Pull Requests before merging.
- Do not force-push shared branches.
- Pull the latest changes before beginning work.
- Avoid editing files owned by other developers without coordination.
- Resolve merge conflicts carefully.
- Never commit secrets or credentials.

Suggested branch names:

- `feature/host-ai`
- `feature/frontend`
- `feature/backend`
- `feature/ai-integrations`
- `feature/voice`
- `fix/bug-description`

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

AI agents must never read, print, copy or expose `.env` contents.

## 7. Coding Rules

Before modifying code:

1. Inspect the relevant files.
2. Understand existing dependencies.
3. Identify possible side effects.
4. Check whether another module depends on the code.

When implementing:

1. Keep changes focused.
2. Follow existing naming conventions.
3. Add appropriate error handling.
4. Add or update tests.
5. Update documentation when necessary.

Do not:
- Rewrite entire modules without justification.
- Remove existing functionality without approval.
- Add fake API responses as real integrations.
- Hardcode credentials.
- Claim tests passed without executing them.

## 8. Testing Requirements

Before submitting changes:

- Run relevant tests.
- Check for broken imports.
- Validate API responses.
- Check error handling.
- Test integration boundaries.
- Report untested functionality honestly.

Every Pull Request should explain:
- What changed.
- Why it changed.
- Files modified.
- Tests performed.
- Known limitations.

## 9. Communication Between Agents

When multiple agents work simultaneously:

- Respect module ownership.
- Agree on API contracts before integration.
- Avoid modifying shared files simultaneously.
- Communicate interface changes.
- Do not assume another agent's implementation is complete.
- Review outputs before integrating them.

## 10. Important Instructions

The repository is the source of truth.

If documentation and actual implementation disagree, inspect the code and report the discrepancy.

Never invent existing functionality.

Never make architectural decisions that conflict with the project's established direction without discussing them with the project lead.

The objective is to build CIDE as a secure, modular, reliable multi-AI orchestration platform.

**Build carefully. Integrate properly. Test everything.**