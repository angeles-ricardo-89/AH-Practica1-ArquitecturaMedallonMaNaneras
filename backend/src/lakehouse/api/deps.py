from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request

from lakehouse.config import Settings
from lakehouse.services.rag_search import search_gold_corpus
from lakehouse.services.security import (
    decode_access_token,
    resolve_csrf_secret,
    resolve_jwt_secret,
    verify_csrf_token,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str
    iat: int


class SearchService:
    async def search(
        self,
        query: str = "",
        top_k: int = 8,
        strategy: str = "hnsw",
        filters: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        _ = strategy
        results = search_gold_corpus(query, top_k)
        if filters:
            filtered = []
            for r in results:
                match = True
                for key, val in filters.items():
                    if key in r and str(r[key]) != val:
                        match = False
                        break
                if match:
                    filtered.append(r)
            results = filtered
        return results, len(results)


async def get_search_service() -> AsyncIterator[SearchService]:
    yield SearchService()


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    secret = resolve_jwt_secret(settings)
    try:
        claims = decode_access_token(
            token,
            secret,
            settings.jwt_issuer,
            settings.jwt_audience,
        )
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    return CurrentUser(
        id=int(claims["sub"]),
        username=claims.get("username", ""),
        role=claims.get("role", "demo"),
        iat=int(claims["iat"]),
    )


def require_csrf(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    token = request.headers.get(settings.csrf_header_name, "")
    secret = resolve_csrf_secret(settings)
    if not verify_csrf_token(token, str(user.id), user.iat, secret):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
