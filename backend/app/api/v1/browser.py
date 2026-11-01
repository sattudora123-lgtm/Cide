from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user, list_params
from app.core.errors import AppError
from app.schemas.models import BrowserJobCreate, BrowserJobPage, BrowserJobPublic, BrowserResultCreate
from app.services.browser_jobs import create_browser_job, submit_browser_result
from app.services.paging import paginate_desc
from app.services.present import present_browser_job
from app.services.state import require_user

router = APIRouter(prefix="/browser-jobs", tags=["browser-jobs"])


@router.post("", status_code=201, response_model=BrowserJobPublic)
def create(body: BrowserJobCreate, request: Request, user: dict = Depends(get_current_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return create_browser_job(db, user["id"], body)


@router.get("", response_model=BrowserJobPage)
def list_jobs(
    request: Request,
    user: dict = Depends(get_current_user),
    page: tuple[int, str | None] = Depends(list_params),
) -> dict:
    limit, cursor = page
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        rows = [present_browser_job(item) for item in db["browser_jobs"] if item["user_id"] == user["id"]]
        selected, next_cursor = paginate_desc(rows, cursor=cursor, limit=limit)
        return {"items": selected, "next_cursor": next_cursor}


@router.get("/{job_id}", response_model=BrowserJobPublic)
def get_job(job_id: UUID, request: Request, user: dict = Depends(get_current_user)) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        job = next(
            (item for item in db["browser_jobs"] if item["id"] == str(job_id) and item["user_id"] == user["id"]),
            None,
        )
        if job is None:
            raise AppError(404, "browser_job_not_found", "Browser job not found")
        return present_browser_job(job)


@router.post("/{job_id}/result", response_model=BrowserJobPublic)
def submit(
    job_id: UUID,
    body: BrowserResultCreate,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    with request.app.state.store.transaction() as db:
        require_user(db, user["id"])
        return submit_browser_result(db, user["id"], str(job_id), body.content)
