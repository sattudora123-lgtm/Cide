from fastapi import APIRouter

from app.api.v1.agents import link, router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.browser import router as browser_router
from app.api.v1.providers import router as providers_router
from app.api.v1.system import router as system_router
from app.api.v1.tasks import router as tasks_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router)
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(link)
api_router.include_router(tasks_router)
api_router.include_router(providers_router)
api_router.include_router(browser_router)
