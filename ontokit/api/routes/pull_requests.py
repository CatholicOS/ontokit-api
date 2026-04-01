"""Pull request management endpoints."""

import hashlib
import hmac
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import OptionalUser, RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.pull_request import (
    BranchCreate,
    BranchInfo,
    BranchListResponse,
    CommentCreate,
    CommentListResponse,
    CommentResponse,
    CommentUpdate,
    GitHubIntegrationCreate,
    GitHubIntegrationResponse,
    GitHubIntegrationUpdate,
    OpenPRsSummary,
    PRCommitListResponse,
    PRCreate,
    PRDiffResponse,
    PRListResponse,
    PRMergeRequest,
    PRMergeResponse,
    PRResponse,
    PRSettingsResponse,
    PRSettingsUpdate,
    PRUpdate,
    ReviewCreate,
    ReviewListResponse,
    ReviewResponse,
)
from ontokit.services.pull_request_service import PullRequestService, get_pull_request_service

logger = logging.getLogger(__name__)

router = APIRouter()


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> PullRequestService:
    """Dependency to get pull request service with database session."""
    return get_pull_request_service(db)


# Global Endpoints (must be before /{project_id}/ routes)


@router.get(
    "/pull-requests/open-summary",
    response_model=OpenPRsSummary,
)
async def get_open_pr_summary(
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> OpenPRsSummary:
    """Get a summary of open pull requests across all projects the user manages."""
    return await service.get_open_pr_summary(user)


# Pull Request Endpoints


@router.get("/{project_id}/pull-requests", response_model=PRListResponse)
async def list_pull_requests(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
    status_filter: str | None = Query(
        default=None, alias="status", description="Filter by status: 'open', 'merged', 'closed'"
    ),
    author_id: str | None = Query(default=None, description="Filter by author user ID"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> PRListResponse:
    """
    List pull requests for a project.

    - Viewers and above can see all PRs
    - Use status filter to show only open, merged, or closed PRs
    - Use author_id filter to show PRs by a specific user
    """
    return await service.list_pull_requests(
        project_id, user, status_filter=status_filter, author_id=author_id, skip=skip, limit=limit
    )


@router.post(
    "/{project_id}/pull-requests",
    response_model=PRResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pull_request(
    project_id: UUID,
    pr: PRCreate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRResponse:
    """
    Create a new pull request.

    - Editors and above can create PRs
    - Source and target branches must exist and be different
    - If GitHub integration is enabled, PR will be synced to GitHub
    """
    return await service.create_pull_request(project_id, pr, user)


@router.get("/{project_id}/pull-requests/{pr_number}", response_model=PRResponse)
async def get_pull_request(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> PRResponse:
    """
    Get a pull request by number.

    Returns full PR details including review and comment counts.
    """
    return await service.get_pull_request(project_id, pr_number, user)


@router.patch("/{project_id}/pull-requests/{pr_number}", response_model=PRResponse)
async def update_pull_request(
    project_id: UUID,
    pr_number: int,
    pr: PRUpdate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRResponse:
    """
    Update a pull request.

    - Only the author, admin, or owner can update
    - Can only update open PRs
    """
    return await service.update_pull_request(project_id, pr_number, pr, user)


@router.post("/{project_id}/pull-requests/{pr_number}/close", response_model=PRResponse)
async def close_pull_request(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRResponse:
    """
    Close a pull request without merging.

    - Only the author, admin, or owner can close
    - Cannot close already closed or merged PRs
    """
    return await service.close_pull_request(project_id, pr_number, user)


@router.post("/{project_id}/pull-requests/{pr_number}/reopen", response_model=PRResponse)
async def reopen_pull_request(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRResponse:
    """
    Reopen a closed pull request.

    - Only the author, admin, or owner can reopen
    - Can only reopen closed PRs (not merged)
    """
    return await service.reopen_pull_request(project_id, pr_number, user)


@router.post("/{project_id}/pull-requests/{pr_number}/merge", response_model=PRMergeResponse)
async def merge_pull_request(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
    merge_request: Annotated[PRMergeRequest, Body()] = PRMergeRequest(),  # noqa: B008
) -> PRMergeResponse:
    """
    Merge a pull request.

    - Only admins and owners can merge
    - PR must be open and meet approval requirements
    - Optionally delete the source branch after merge
    """
    # Capture target branch before merge for post-merge processing
    pr_info = await service.get_pull_request(project_id, pr_number, user)
    target_branch = pr_info.target_branch

    result = await service.merge_pull_request(project_id, pr_number, merge_request, user)

    # Trigger ontology index rebuild for the target branch after merge
    if result.success:
        try:
            from ontokit.api.utils.redis import get_arq_pool

            pool = await get_arq_pool()
            if pool is not None:
                await pool.enqueue_job(
                    "run_ontology_index_task",
                    str(project_id),
                    target_branch,
                    result.merge_commit_hash,
                )
        except Exception:
            logger.warning("Failed to queue ontology re-index after PR merge", exc_info=True)

    return result


# Review Endpoints


@router.get(
    "/{project_id}/pull-requests/{pr_number}/reviews",
    response_model=ReviewListResponse,
)
async def list_reviews(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> ReviewListResponse:
    """
    List reviews for a pull request.
    """
    return await service.list_reviews(project_id, pr_number, user)


@router.post(
    "/{project_id}/pull-requests/{pr_number}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    project_id: UUID,
    pr_number: int,
    review: ReviewCreate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> ReviewResponse:
    """
    Create a review on a pull request.

    - Only admins and owners can approve or request changes
    - Anyone with view access can leave a comment review
    - Cannot review closed or merged PRs
    """
    return await service.create_review(project_id, pr_number, review, user)


# Comment Endpoints


@router.get(
    "/{project_id}/pull-requests/{pr_number}/comments",
    response_model=CommentListResponse,
)
async def list_comments(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> CommentListResponse:
    """
    List comments for a pull request.

    Returns top-level comments with their replies nested.
    """
    return await service.list_comments(project_id, pr_number, user)


@router.post(
    "/{project_id}/pull-requests/{pr_number}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    project_id: UUID,
    pr_number: int,
    comment: CommentCreate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> CommentResponse:
    """
    Create a comment on a pull request.

    - Anyone with view access can comment
    - Use parent_id to create a reply to an existing comment
    """
    return await service.create_comment(project_id, pr_number, comment, user)


@router.patch(
    "/{project_id}/pull-requests/{pr_number}/comments/{comment_id}",
    response_model=CommentResponse,
)
async def update_comment(
    project_id: UUID,
    pr_number: int,
    comment_id: UUID,
    comment: CommentUpdate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> CommentResponse:
    """
    Update a comment.

    Only the author can edit their comment.
    """
    return await service.update_comment(project_id, pr_number, comment_id, comment, user)


@router.delete(
    "/{project_id}/pull-requests/{pr_number}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    project_id: UUID,
    pr_number: int,
    comment_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """
    Delete a comment.

    - Authors can delete their own comments
    - Admins and owners can delete any comment
    """
    await service.delete_comment(project_id, pr_number, comment_id, user)


# PR Commits and Diff


@router.get(
    "/{project_id}/pull-requests/{pr_number}/commits",
    response_model=PRCommitListResponse,
)
async def get_pr_commits(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> PRCommitListResponse:
    """
    Get commits included in a pull request.

    Returns commits that are in the source branch but not in the target branch.
    """
    return await service.get_pr_commits(project_id, pr_number, user)


@router.get(
    "/{project_id}/pull-requests/{pr_number}/diff",
    response_model=PRDiffResponse,
)
async def get_pr_diff(
    project_id: UUID,
    pr_number: int,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> PRDiffResponse:
    """
    Get the file diff for a pull request.

    Shows which files were added, modified, or deleted.
    """
    return await service.get_pr_diff(project_id, pr_number, user)


# Branch Endpoints


@router.get("/{project_id}/branches", response_model=BranchListResponse)
async def list_branches(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: OptionalUser,
) -> BranchListResponse:
    """
    List branches for a project.

    Returns all branches with their current commit and ahead/behind counts.
    """
    return await service.list_branches(project_id, user)


@router.post(
    "/{project_id}/branches",
    response_model=BranchInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_branch(
    project_id: UUID,
    branch: BranchCreate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> BranchInfo:
    """
    Create a new branch.

    - Editors and above can create branches
    - Branch names must match pattern: letters, numbers, underscores, hyphens, slashes
    - Optionally specify a base branch (defaults to current branch)
    """
    return await service.create_branch(project_id, branch, user)


@router.post("/{project_id}/branches/{branch_name}/checkout", response_model=BranchInfo)
async def switch_branch(
    project_id: UUID,
    branch_name: str,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> BranchInfo:
    """
    Switch to a different branch.

    - Editors and above can switch branches
    - The working directory will be updated to reflect the branch contents
    """
    return await service.switch_branch(project_id, branch_name, user)


# GitHub Integration Endpoints


@router.get("/{project_id}/github-integration", response_model=GitHubIntegrationResponse | None)
async def get_github_integration(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> GitHubIntegrationResponse | None:
    """
    Get GitHub integration settings.

    Only admins and owners can view integration settings.
    Returns null if no integration is configured.
    """
    return await service.get_github_integration(project_id, user)


@router.post(
    "/{project_id}/github-integration",
    response_model=GitHubIntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_github_integration(
    project_id: UUID,
    integration: GitHubIntegrationCreate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> GitHubIntegrationResponse:
    """
    Setup GitHub integration for a project.

    - Only the project owner can setup integration
    - Requires a GitHub App installation ID for the target repository
    - A webhook secret will be generated automatically
    """
    return await service.create_github_integration(project_id, integration, user)


@router.patch("/{project_id}/github-integration", response_model=GitHubIntegrationResponse)
async def update_github_integration(
    project_id: UUID,
    integration: GitHubIntegrationUpdate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> GitHubIntegrationResponse:
    """
    Update GitHub integration settings.

    Only the project owner can update settings.
    """
    return await service.update_github_integration(project_id, integration, user)


@router.get("/{project_id}/github-integration/webhook-secret")
async def get_webhook_secret(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> dict[str, str | None]:
    """
    Retrieve the webhook secret for configuring GitHub webhooks.

    Only the project owner can view the secret.
    """
    return await service.get_webhook_secret(project_id, user)


@router.post("/{project_id}/github-integration/webhook-setup")
async def setup_webhook(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> dict[str, str | int | None]:
    """
    Auto-detect or auto-create a GitHub webhook for the project.

    Uses the user's PAT to check for existing hooks or create one.
    Requires the admin:repo_hook scope on the PAT for auto-creation.
    """
    return await service.setup_or_detect_webhook(project_id, user)


@router.delete(
    "/{project_id}/github-integration",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_github_integration(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """
    Remove GitHub integration for a project.

    Only the project owner can remove integration.
    """
    await service.delete_github_integration(project_id, user)


# PR Settings Endpoints


@router.get("/{project_id}/pr-settings", response_model=PRSettingsResponse)
async def get_pr_settings(
    project_id: UUID,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRSettingsResponse:
    """
    Get PR workflow settings.

    Only admins and owners can view settings.
    """
    return await service.get_pr_settings(project_id, user)


@router.patch("/{project_id}/pr-settings", response_model=PRSettingsResponse)
async def update_pr_settings(
    project_id: UUID,
    settings: PRSettingsUpdate,
    service: Annotated[PullRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PRSettingsResponse:
    """
    Update PR workflow settings.

    Only the project owner can update settings.
    - pr_approval_required: 0 = no approval needed, 1+ = minimum approvals before merge
    """
    return await service.update_pr_settings(project_id, settings, user)


# GitHub Webhook Endpoint


@router.post("/webhooks/github/{project_id}")
async def github_webhook(
    project_id: UUID,
    request: Request,
    service: Annotated[PullRequestService, Depends(get_service)],
    x_hub_signature_256: str = Header(...),
    x_github_event: str = Header(...),
) -> dict[str, str]:
    """
    Handle GitHub webhook events.

    This endpoint receives webhook events from GitHub and syncs local PR state.
    The webhook signature is verified using the project's webhook secret.
    """
    # Get raw body for signature verification
    body = await request.body()

    # Get integration to verify signature
    from sqlalchemy import select

    from ontokit.models.pull_request import GitHubIntegration

    result = await service.db.execute(
        select(GitHubIntegration).where(GitHubIntegration.project_id == project_id)
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub integration not found",
        )

    if not integration.webhooks_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhooks are not enabled for this integration",
        )

    if not integration.webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret is not configured",
        )

    # Verify signature
    expected_signature = (
        "sha256="
        + hmac.new(
            integration.webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(x_hub_signature_256, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    # Parse payload
    import json

    payload = json.loads(body)

    # Handle events
    if x_github_event == "pull_request":
        await service.handle_github_pr_webhook(
            project_id,
            payload.get("action", ""),
            payload.get("pull_request", {}),
        )
    elif x_github_event == "pull_request_review":
        await service.handle_github_review_webhook(
            project_id,
            payload.get("action", ""),
            payload.get("review", {}),
            payload.get("pull_request", {}),
        )
    elif x_github_event == "push":
        await service.handle_github_push_webhook(
            project_id,
            payload.get("ref", ""),
            payload.get("commits", []),
        )

        # Trigger upstream sync if configured for webhook frequency
        ref = payload.get("ref", "")
        if ref.startswith("refs/heads/"):
            push_branch = ref[len("refs/heads/") :]
            commits = payload.get("commits", [])

            from ontokit.models.upstream_sync import UpstreamSyncConfig

            sync_result = await service.db.execute(
                select(UpstreamSyncConfig).where(
                    UpstreamSyncConfig.project_id == project_id,
                    UpstreamSyncConfig.enabled.is_(True),
                    UpstreamSyncConfig.frequency == "webhook",
                )
            )
            sync_config = sync_result.scalar_one_or_none()

            if sync_config and sync_config.branch == push_branch:
                # Check if any commit touches the tracked file
                touched_files: set[str] = set()
                for commit in commits:
                    touched_files.update(commit.get("added", []))
                    touched_files.update(commit.get("modified", []))

                if sync_config.file_path in touched_files:
                    from ontokit.api.utils.redis import get_arq_pool

                    sync_config.status = "checking"
                    await service.db.commit()

                    pool = await get_arq_pool()
                    await pool.enqueue_job("run_upstream_check_task", str(project_id))

    return {"status": "ok"}
