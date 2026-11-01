from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import client_host, get_current_user
from app.schemas.models import LoginRequest, RefreshRequest, RegisterRequest, TokenPair, UserPublic
from app.services.auth import login_user, logout_session, refresh_session, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=UserPublic)
def register(request: Request, body: RegisterRequest) -> dict:
    request.app.state.rate_limiter.check(f"auth:{client_host(request)}")
    with request.app.state.store.transaction() as db:
        return register_user(db, email=body.email, password=body.password, display_name=body.display_name)


@router.post("/login", response_model=TokenPair)
def login(request: Request, body: LoginRequest) -> dict:
    request.app.state.rate_limiter.check(f"auth:{client_host(request)}")
    with request.app.state.store.transaction() as db:
        return login_user(
            db,
            request.app.state.settings,
            email=body.email,
            password=body.password,
            dummy_password_hash=request.app.state.dummy_password_hash,
        )


@router.post("/refresh", response_model=TokenPair)
def refresh(request: Request, body: RefreshRequest) -> dict:
    with request.app.state.store.transaction() as db:
        return refresh_session(db, request.app.state.settings, body.refresh_token)


@router.post("/logout", status_code=204)
def logout(request: Request, body: RefreshRequest, user: dict = Depends(get_current_user)) -> Response:
    with request.app.state.store.transaction() as db:
        logout_session(db, user["id"], body.refresh_token)
    return Response(status_code=204)


@router.get("/me", response_model=UserPublic)
def me(user: dict = Depends(get_current_user)) -> dict:
    return user
