from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.api.deps import list_params, require_entitled_user
from app.core.errors import AppError
from app.schemas.models import (
    AssignRequest,
    StepPublic,
    TaskCreate,
    TaskDetail,
    TaskPage,
    TaskPublic,
    WorkflowCreate,
    WorkflowPublic,
    EventPage,
)
from app.services.execution import dispatch
from app.services.paging import paginate_desc
from app.services.present import present_step, present_task
from app.services.state import get_step, get_task, require_user
from app.services.tasks import (
    approve_step,
    assign_step,
    cancel_task,
    create_task,
    create_workflow,
    deny_step,
    list_events,
    task_detail,
)

router = APIRouter(tags=["tasks"])


def _clock(request: Request) -> tuple[datetime, int]:
    return datetime.now(UTC), request.app.state.settings.heartbeat_stale_seconds


@router.post("/tasks", status_code=201, response_model=TaskPublic)
def create(
    request: Request,
    body: TaskCreate,
    user: dict = Depends(require_entitled_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return create_task(db, user["id"], body, idempotency_key, datetime.now(UTC))


@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    request: Request,
    user: dict = Depends(require_entitled_user),
    page: tuple[int, str | None] = Depends(list_params),
) -> dict:
    limit, cursor = page
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        rows = [item for item in db["tasks"] if item["user_id"] == user["id"]]
        selected, next_cursor = paginate_desc(rows, cursor=cursor, limit=limit)
        return {"items": [present_task(item) for item in selected], "next_cursor": next_cursor}


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task_detail(task_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return task_detail(db, user["id"], str(task_id), now, stale)


@router.post("/tasks/{task_id}/cancel", response_model=TaskPublic)
def cancel(task_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return cancel_task(db, user["id"], str(task_id))


@router.post("/tasks/{task_id}/plan")
def plan(task_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> None:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        get_task(db, user["id"], str(task_id))
    raise AppError(
        501,
        "host_planner_not_configured",
        "Host AI planning is not implemented. Submit an explicit workflow.",
    )


@router.post("/tasks/{task_id}/workflow", status_code=201, response_model=WorkflowPublic)
def add_workflow(
    task_id: UUID,
    body: WorkflowCreate,
    request: Request,
    user: dict = Depends(require_entitled_user),
) -> dict:
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return create_workflow(db, user["id"], str(task_id), body, now, stale)


@router.get("/tasks/{task_id}/events", response_model=EventPage)
def events(
    task_id: UUID,
    request: Request,
    user: dict = Depends(require_entitled_user),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return list_events(db, user["id"], str(task_id), after=after, limit=limit)


@router.post("/steps/{step_id}/assign", response_model=StepPublic)
def assign(
    step_id: UUID,
    body: AssignRequest,
    request: Request,
    user: dict = Depends(require_entitled_user),
) -> dict:
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return assign_step(db, user["id"], str(step_id), str(body.agent_id), now, stale)


@router.post("/steps/{step_id}/approve", response_model=StepPublic)
def approve(step_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return approve_step(db, user["id"], str(step_id), now, stale)


@router.post("/steps/{step_id}/deny", response_model=StepPublic)
def deny(step_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return deny_step(db, user["id"], str(step_id), now, stale)


@router.post("/steps/{step_id}/dispatch", response_model=StepPublic)
async def dispatch_step(step_id: UUID, request: Request, user: dict = Depends(require_entitled_user)) -> dict:
    await dispatch(
        store=request.app.state.store,
        settings=request.app.state.settings,
        http=request.app.state.http,
        user_id=user["id"],
        step_id=str(step_id),
    )
    now, stale = _clock(request)
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return present_step(db, get_step(db, user["id"], str(step_id)), now, stale)
