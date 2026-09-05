from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from lakehouse.api.deps import CurrentUser, SettingsDep, get_current_user, require_csrf
from lakehouse.schemas.auth import LoginRequest, LoginResponse, MeResponse
from lakehouse.services.rate_limit import is_allowed, minute_window_start, retry_after_seconds
from lakehouse.services.security import (
    create_access_token,
    create_csrf_token,
    decode_access_token,
    hmac_digest,
    resolve_csrf_secret,
    resolve_jwt_secret,
    verify_password,
)

if TYPE_CHECKING:
    from lakehouse.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _pg_conn_str(settings: Settings) -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and set JWT cookie",
    description="Validates demo credentials and sets an HttpOnly JWT cookie plus a CSRF token",
)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    settings: SettingsDep,
) -> LoginResponse:
    ip = request.client.host if request.client else "unknown"
    ip_hmac = hmac_digest(resolve_csrf_secret(settings), ip)
    rate_key = f"login:{ip_hmac}:{payload.username}"
    if not is_allowed(
        _pg_conn_str(settings), rate_key, minute_window_start(), settings.login_rate_limit
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after_seconds())},
        )

    with psycopg.connect(_pg_conn_str(settings)) as conn:
        row = conn.execute(
            "SELECT id, password_hash, role FROM app_user WHERE username = %s",
            (payload.username,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row[1]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id, _password_hash, role = row
    secret = resolve_jwt_secret(settings)
    token = create_access_token(
        user_id=user_id,
        username=payload.username,
        role=role,
        secret=secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.jwt_expire_minutes,
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )

    claims = decode_access_token(token, secret, settings.jwt_issuer, settings.jwt_audience)
    csrf = create_csrf_token(str(user_id), int(claims["iat"]), resolve_csrf_secret(settings))
    return LoginResponse(csrf_token=csrf)


@router.post(
    "/logout",
    summary="Logout and clear cookie",
    description="Clears the JWT cookie; requires authentication and CSRF",
    dependencies=[Depends(require_csrf)],
)
def logout(response: Response, settings: SettingsDep) -> dict[str, str]:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return {"status": "ok"}


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current identity",
    description="Returns the identity of the authenticated user",
)
def me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, username=user.username, role=user.role)
