"""Anonymous suggestion session endpoints.

Provides create/save/submit/discard/beacon endpoints for unauthenticated users.
All endpoints are gated on AUTH_MODE != "required".
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.anonymous_token import verify_anonymous_token
from ontokit.core.config import settings
from ontokit.core.database import get_db
from ontokit.schemas.anonymous_suggestion import (
    AnonymousSessionCreateResponse,
    AnonymousSubmitRequest,
    AnonymousSubmitResponse,
)
from ontokit.schemas.suggestion import (
    SuggestionBeaconRequest,
    SuggestionSaveRequest,
    SuggestionSaveResponse,
)
from ontokit.services.suggestion_service import SuggestionService, get_suggestion_service

router = APIRouter()


def _require_anonymous_mode() -> None:
    """Raise 403 if anonymous suggestions are not enabled."""
    from fastapi import HTTPException

    if settings.auth_mode == "required":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anonymous suggestions not available",
        )


def _verify_anon_token(x_anonymous_token: str) -> str:
    """Verify the X-Anonymous-Token header and return the session_id.

    Raises 401 if the token is missing, invalid, or expired.
    """
    from fastapi import HTTPException

    verified = verify_anonymous_token(x_anonymous_token)
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired anonymous token",
        )
    return verified


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> SuggestionService:
    """Dependency to get suggestion service with database session."""
    return get_suggestion_service(db)


@router.post(
    "/{project_id}/suggestions/anonymous/sessions",
    response_model=AnonymousSessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_anonymous_session(
    project_id: UUID,
    request: Request,
    service: Annotated[SuggestionService, Depends(get_service)],
) -> AnonymousSessionCreateResponse:
    """Create a new anonymous suggestion session.

    No authentication required. Rate-limited to 5 sessions per IP per hour.
    Only available when AUTH_MODE is not "required".
    """
    _require_anonymous_mode()
    client_ip = request.client.host if request.client else "unknown"
    return await service.create_anonymous_session(project_id, client_ip)


@router.put(
    "/{project_id}/suggestions/anonymous/sessions/{session_id}/save",
    response_model=SuggestionSaveResponse,
)
async def save_anonymous_session(
    project_id: UUID,
    session_id: str,
    data: SuggestionSaveRequest,
    service: Annotated[SuggestionService, Depends(get_service)],
    x_anonymous_token: Annotated[str, Header()],
) -> SuggestionSaveResponse:
    """Save content to an anonymous suggestion session.

    Authenticated via X-Anonymous-Token header.
    """
    _require_anonymous_mode()
    verified_session_id = _verify_anon_token(x_anonymous_token)
    return await service.save_anonymous(project_id, session_id, data, verified_session_id)


@router.post(
    "/{project_id}/suggestions/anonymous/sessions/{session_id}/submit",
    response_model=AnonymousSubmitResponse,
)
async def submit_anonymous_session(
    project_id: UUID,
    session_id: str,
    data: AnonymousSubmitRequest,
    service: Annotated[SuggestionService, Depends(get_service)],
    x_anonymous_token: Annotated[str, Header()],
) -> AnonymousSubmitResponse:
    """Submit an anonymous suggestion session as a pull request.

    Authenticated via X-Anonymous-Token header.
    Honeypot field ('website') triggers silent fake success for bot detection.
    """
    _require_anonymous_mode()
    verified_session_id = _verify_anon_token(x_anonymous_token)

    # Honeypot check: bots fill the 'website' field, humans leave it blank
    if data.honeypot is not None and data.honeypot != "":
        # Silent fake success — do not create anything
        return AnonymousSubmitResponse(pr_number=0, pr_url=None, status="submitted")

    return await service.submit_anonymous(project_id, session_id, data, verified_session_id)


@router.post(
    "/{project_id}/suggestions/anonymous/sessions/{session_id}/discard",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def discard_anonymous_session(
    project_id: UUID,
    session_id: str,
    service: Annotated[SuggestionService, Depends(get_service)],
    x_anonymous_token: Annotated[str, Header()],
) -> Response:
    """Discard an anonymous suggestion session and delete its branch.

    Authenticated via X-Anonymous-Token header.
    """
    _require_anonymous_mode()
    verified_session_id = _verify_anon_token(x_anonymous_token)
    await service.discard_anonymous(project_id, session_id, verified_session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/suggestions/anonymous/beacon",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def anonymous_beacon_save(
    project_id: UUID,
    data: SuggestionBeaconRequest,
    service: Annotated[SuggestionService, Depends(get_service)],
    token: str = Query(..., description="Anonymous session token for authentication"),
) -> Response:
    """Handle a sendBeacon flush for anonymous sessions.

    Authenticated via 'token' query parameter (same pattern as authenticated beacon).
    """
    _require_anonymous_mode()
    verified_session_id = verify_anonymous_token(token)
    if verified_session_id is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired anonymous token",
        )
    # Delegate to the existing beacon_save (session lookup is by session_id, no user check)
    await service.beacon_save(project_id, data, data.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
