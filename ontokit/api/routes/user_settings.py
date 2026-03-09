"""User settings endpoints for GitHub token management."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import RequiredUser
from ontokit.core.database import get_db
from ontokit.core.encryption import decrypt_token, encrypt_token
from ontokit.models.user_github_token import UserGitHubToken
from ontokit.schemas.user_settings import (
    GitHubRepoInfo,
    GitHubRepoListResponse,
    GitHubTokenCreate,
    GitHubTokenResponse,
    GitHubTokenStatus,
    UserSearchResponse,
    UserSearchResult,
)
from ontokit.services.github_service import GitHubService, get_github_service
from ontokit.services.user_service import UserService, get_user_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _token_preview(encrypted: str) -> str:
    """Return a masked preview of the decrypted token (first 4 + last 4 chars)."""
    try:
        plain = decrypt_token(encrypted)
        if len(plain) > 8:
            return f"{plain[:4]}...{plain[-4:]}"
        return "****"
    except Exception:
        return "****"


@router.get("/me/github-token", response_model=GitHubTokenStatus)
async def get_github_token_status(
    user: RequiredUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GitHubTokenStatus:
    """Check whether the authenticated user has a stored GitHub token."""
    result = await db.execute(select(UserGitHubToken).where(UserGitHubToken.user_id == user.id))
    token_row = result.scalar_one_or_none()
    if not token_row:
        return GitHubTokenStatus(has_token=False)
    return GitHubTokenStatus(
        has_token=True,
        github_username=token_row.github_username,
    )


@router.post(
    "/me/github-token", response_model=GitHubTokenResponse, status_code=status.HTTP_201_CREATED
)
async def save_github_token(
    body: GitHubTokenCreate,
    user: RequiredUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> GitHubTokenResponse:
    """Validate a GitHub PAT and store it (encrypted) for the authenticated user.

    The token is validated via GET /user. It must include the `repo` scope.
    If the user already has a token, it is replaced (upsert).
    """
    # Validate the token against GitHub
    try:
        username, scopes = await github_service.get_authenticated_user(body.token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid GitHub token: {e}",
        ) from e

    # Check for repo scope
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if "repo" not in scope_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token must include the 'repo' scope. Found scopes: {scopes}",
        )

    encrypted = encrypt_token(body.token)

    # Upsert: check if row exists
    result = await db.execute(select(UserGitHubToken).where(UserGitHubToken.user_id == user.id))
    token_row = result.scalar_one_or_none()

    if token_row:
        token_row.encrypted_token = encrypted
        token_row.github_username = username
        token_row.token_scopes = scopes
    else:
        token_row = UserGitHubToken(
            user_id=user.id,
            encrypted_token=encrypted,
            github_username=username,
            token_scopes=scopes,
        )
        db.add(token_row)

    await db.commit()
    await db.refresh(token_row)

    return GitHubTokenResponse(
        github_username=token_row.github_username,
        token_scopes=token_row.token_scopes,
        token_preview=_token_preview(token_row.encrypted_token),
        created_at=token_row.created_at,
        updated_at=token_row.updated_at,
    )


@router.delete("/me/github-token", status_code=status.HTTP_204_NO_CONTENT)
async def delete_github_token(
    user: RequiredUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove the stored GitHub token for the authenticated user."""
    result = await db.execute(select(UserGitHubToken).where(UserGitHubToken.user_id == user.id))
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub token found",
        )
    await db.delete(token_row)
    await db.commit()


@router.get("/me/github-repos", response_model=GitHubRepoListResponse)
async def list_github_repos(
    user: RequiredUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    github_service: Annotated[GitHubService, Depends(get_github_service)],
    q: str | None = Query(default=None, description="Search query to filter repos"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> GitHubRepoListResponse:
    """List GitHub repositories accessible to the user's stored PAT.

    Supports optional `?q=` search query for filtering.
    """
    # Get the user's token
    result = await db.execute(select(UserGitHubToken).where(UserGitHubToken.user_id == user.id))
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub token found. Connect your GitHub account in Settings first.",
        )

    token = decrypt_token(token_row.encrypted_token)

    try:
        repos = await github_service.list_user_repos(
            token=token, query=q, page=page, per_page=per_page
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repos from GitHub: {e}",
        ) from e

    items = [
        GitHubRepoInfo(
            full_name=r.get("full_name", ""),
            owner=r.get("owner", {}).get("login", ""),
            name=r.get("name", ""),
            description=r.get("description"),
            private=r.get("private", False),
            default_branch=r.get("default_branch", "main"),
            html_url=r.get("html_url", ""),
        )
        for r in repos
    ]

    return GitHubRepoListResponse(items=items, total=len(items))


@router.get("/search", response_model=UserSearchResponse)
async def search_users(
    user: RequiredUser,  # noqa: ARG001
    user_service: Annotated[UserService, Depends(get_user_service)],
    q: str = Query(..., min_length=2, description="Search query for username, email, or name"),
    limit: int = Query(default=10, ge=1, le=50),
) -> UserSearchResponse:
    """Search Zitadel users by username, email, or display name.

    Requires authentication. Returns matching users for the add-member autocomplete.
    """
    results, total = await user_service.search_users(query=q, limit=limit)

    items = [
        UserSearchResult(
            id=r.get("id") or "",
            username=r.get("username") or "",
            display_name=r.get("display_name"),
            email=r.get("email"),
        )
        for r in results
    ]

    return UserSearchResponse(items=items, total=total)
