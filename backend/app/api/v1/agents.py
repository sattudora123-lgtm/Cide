from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import list_params, require_entitled_agent, require_entitled_user
from app.schemas.models import (
    AgentCreated,
    AgentCreate,
    AgentEventRequest,
    AgentEventResult,
    AgentPage,
    AgentPatch,
    AgentPublic,
    AssignmentPage,
    HeartbeatRequest,
    HeartbeatResponse,
    TokenOnce,
)
from app.services.agents import (
    accept_agent_event,
    create_agent,
    disable_agent,
    list_assignments,
    record_heartbeat,
    rotate_agent_token,
    update_agent,
)
from app.services.paging import paginate_desc
from app.services.present import present_agent
from app.services.state import get_agent, require_user

router = APIRouter(tags=["agents"])


def _now_and_stale(request: Request) -> tuple[datetime, int]:
    return datetime.now(UTC), request.app.state.settings.heartbeat_stale_seconds


@router.post("/agents", status_code=201, response_model=AgentCreated)
def create(request: Request, body: AgentCreate, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _now_and_stale(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        created = create_agent(db, user["id"], body)
        agent = get_agent(db, user["id"], created["id"])
        return {"agent": present_agent(agent, db["steps"], now, stale), "token": created["token"]}


@router.get("/agents", response_model=AgentPage)
def list_agents(
    request: Request,
    user: dict = Depends(require_entitled_user),
    page: tuple[int, str | None] = Depends(list_params),
) -> dict:
    now, stale = _now_and_stale(request)
    limit, cursor = page
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        rows = [item for item in db["agents"] if item["user_id"] == user["id"]]
        selected, next_cursor = paginate_desc(rows, cursor=cursor, limit=limit)
        return {
            "items": [present_agent(item, db["steps"], now, stale) for item in selected],
            "next_cursor": next_cursor,
        }


@router.get("/agents/{agent_id}", response_model=AgentPublic)
def get_one(agent_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _now_and_stale(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return present_agent(get_agent(db, user["id"], str(agent_id)), db["steps"], now, stale)


@router.patch("/agents/{agent_id}", response_model=AgentPublic)
def patch(agent_id: UUID, body: AgentPatch, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _now_and_stale(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        agent = update_agent(db, user["id"], str(agent_id), body)
        return present_agent(agent, db["steps"], now, stale)


@router.post("/agents/{agent_id}/disable", response_model=AgentPublic)
def disable(agent_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _now_and_stale(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        agent = disable_agent(db, user["id"], str(agent_id))
        return present_agent(agent, db["steps"], now, stale)


@router.post("/agents/{agent_id}/rotate-token", response_model=TokenOnce)
def rotate(agent_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return {"token": rotate_agent_token(db, user["id"], str(agent_id))}


link = APIRouter(prefix="/agent-link", tags=["agent-link"])


@link.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(body: HeartbeatRequest, request: Request, agent: dict = Depends(require_entitled_agent)) -> dict:
    now, stale = _now_and_stale(request)
    with request.app.state.store.transaction() as db:
        stored = record_heartbeat(db, agent["id"], body.state)
        presented = present_agent(stored, db["steps"], now, stale)
        return {"status": presented["status"], "last_heartbeat_at": presented["last_heartbeat_at"]}


@link.get("/assignments", response_model=AssignmentPage)
def assignments(
    request: Request,
    agent: dict = Depends(require_entitled_agent),
    page: tuple[int, str | None] = Depends(list_params),
) -> dict:
    limit, cursor = page
    with request.app.state.store.transaction() as db:
        rows = list_assignments(db, agent)
        selected, next_cursor = paginate_desc(rows, cursor=cursor, limit=limit)
        return {"items": selected, "next_cursor": next_cursor}


@link.post("/events", response_model=AgentEventResult)
def post_event(
    body: AgentEventRequest,
    request: Request,
    agent: dict = Depends(require_entitled_agent),
) -> dict:
    with request.app.state.store.transaction() as db:
        step = accept_agent_event(db, agent, body)
        return {"step_id": step["id"], "status": step["status"]}
