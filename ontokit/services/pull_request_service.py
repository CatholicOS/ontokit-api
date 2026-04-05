"""Pull request service for managing PRs, reviews, comments, and branches."""

import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ontokit.core.auth import CurrentUser
from ontokit.core.encryption import decrypt_token
from ontokit.git import GitRepositoryService, get_git_service
from ontokit.models.branch_metadata import BranchMetadata
from ontokit.models.project import Project, ProjectMember
from ontokit.models.pull_request import (
    GitHubIntegration,
    PRStatus,
    PullRequest,
    PullRequestComment,
    PullRequestReview,
    ReviewStatus,
)
from ontokit.models.remote_sync import RemoteSyncConfig
from ontokit.models.user_github_token import UserGitHubToken
from ontokit.schemas.project import ProjectRole
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
    PRCommit,
    PRCommitListResponse,
    PRCreate,
    PRDiffResponse,
    PRFileChange,
    PRListResponse,
    PRMergeRequest,
    PRMergeResponse,
    ProjectOpenPRCount,
    PRResponse,
    PRSettingsResponse,
    PRSettingsUpdate,
    PRUpdate,
    PRUser,
    ReviewCreate,
    ReviewListResponse,
    ReviewResponse,
)
from ontokit.services.github_service import GitHubService, get_github_service
from ontokit.services.notification_service import NotificationService
from ontokit.services.user_service import UserService, get_user_service

logger = logging.getLogger(__name__)


class PullRequestService:
    """Service for pull request CRUD operations, reviews, and comments."""

    def __init__(
        self,
        db: AsyncSession,
        git_service: GitRepositoryService | None = None,
        github_service: GitHubService | None = None,
        user_service: UserService | None = None,
    ) -> None:
        self.db = db
        self.git_service = git_service or get_git_service()
        self.github_service = github_service or get_github_service()
        self.user_service = user_service or get_user_service()

    async def _sync_merge_commits_to_prs(self, project_id: UUID) -> None:
        """Sync merge commits from git history to PR records.

        This creates PR records for merge commits that were done directly
        via git (bypassing the PR workflow), and also backfills commit hashes
        for existing merged PRs that are missing them.
        """
        try:
            # Get revision history with merge commits
            history = self.git_service.get_history(project_id, limit=100)
        except Exception as e:
            logger.warning(f"Failed to get revision history for PR sync: {e}")
            return

        # Build a map of merge commits by source branch name
        merge_commits_by_branch: dict[str, Any] = {}
        for commit in history:
            if (
                commit.is_merge
                and commit.merged_branch
                and commit.merged_branch not in merge_commits_by_branch
            ):
                # Only keep the most recent merge for each branch
                merge_commits_by_branch[commit.merged_branch] = commit

        # Get all existing merged PRs for this project
        result = await self.db.execute(
            select(PullRequest).where(
                PullRequest.project_id == project_id,
                PullRequest.status == PRStatus.MERGED.value,
            )
        )
        existing_prs = {pr.source_branch: pr for pr in result.scalars().all()}

        # Backfill commit hashes for existing PRs that are missing them
        prs_updated = False
        for source_branch, pr in existing_prs.items():
            if pr.merge_commit_hash and pr.base_commit_hash and pr.head_commit_hash:
                # Already has all commit hashes
                continue

            # Try to find matching merge commit
            if source_branch in merge_commits_by_branch:
                commit = merge_commits_by_branch[source_branch]

                # Extract commit hashes from merge commit parents
                base_commit_hash = (
                    commit.parent_hashes[0] if len(commit.parent_hashes) > 0 else None
                )
                head_commit_hash = (
                    commit.parent_hashes[1] if len(commit.parent_hashes) > 1 else None
                )

                # Update PR with commit hashes
                if not pr.merge_commit_hash:
                    pr.merge_commit_hash = commit.hash
                if not pr.base_commit_hash and base_commit_hash:
                    pr.base_commit_hash = base_commit_hash
                if not pr.head_commit_hash and head_commit_hash:
                    pr.head_commit_hash = head_commit_hash

                # Backfill author name/email if missing
                if not pr.author_name:
                    pr.author_name = commit.author_name
                if not pr.author_email:
                    pr.author_email = commit.author_email

                prs_updated = True
                logger.info(
                    f"Backfilled commit hashes for PR #{pr.pr_number} "
                    f"'{source_branch}' (merge commit {commit.short_hash})"
                )

        # Get max PR number for creating new PRs
        max_number_result = await self.db.execute(
            select(func.max(PullRequest.pr_number)).where(PullRequest.project_id == project_id)
        )
        next_pr_number = (max_number_result.scalar() or 0) + 1

        # Create new PRs for merge commits that don't have corresponding PRs
        new_prs_created = False
        for merged_branch, commit in merge_commits_by_branch.items():
            # Skip if we already have a PR for this branch
            if merged_branch in existing_prs:
                continue

            # Parse the merge timestamp
            try:
                merged_at = datetime.fromisoformat(commit.timestamp.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                merged_at = datetime.now(UTC)

            # Extract commit hashes from merge commit parents
            base_commit_hash = commit.parent_hashes[0] if len(commit.parent_hashes) > 0 else None
            head_commit_hash = commit.parent_hashes[1] if len(commit.parent_hashes) > 1 else None

            # Create a retroactive PR record
            db_pr = PullRequest(
                project_id=project_id,
                pr_number=next_pr_number,
                title=f"Merge branch '{merged_branch}'",
                description=f"Retroactively created PR for direct git merge.\n\nOriginal commit: {commit.hash}\nMessage: {commit.message}",
                source_branch=merged_branch,
                target_branch="main",  # Assume main as target for direct merges
                author_id=commit.author_email,  # Use email as author identifier
                author_name=commit.author_name,
                author_email=commit.author_email,
                status=PRStatus.MERGED.value,
                merged_by=commit.author_email,
                merged_at=merged_at,
                merge_commit_hash=commit.hash,
                base_commit_hash=base_commit_hash,
                head_commit_hash=head_commit_hash,
            )
            self.db.add(db_pr)

            # Track this in existing_prs to avoid duplicates in this batch
            existing_prs[merged_branch] = db_pr
            next_pr_number += 1
            new_prs_created = True

            logger.info(
                f"Created retroactive PR #{db_pr.pr_number} for merge of "
                f"'{merged_branch}' (commit {commit.short_hash})"
            )

        if new_prs_created or prs_updated:
            await self.db.commit()

    # Pull Request CRUD

    async def create_pull_request(
        self, project_id: UUID, pr_create: PRCreate, user: CurrentUser
    ) -> PRResponse:
        """Create a new pull request."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin", "editor"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only editors and above can create pull requests",
            )

        # Verify source branch exists
        branches = self.git_service.list_branches(project_id)
        branch_names = [b.name for b in branches]

        if pr_create.source_branch not in branch_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source branch '{pr_create.source_branch}' does not exist",
            )

        if pr_create.target_branch not in branch_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target branch '{pr_create.target_branch}' does not exist",
            )

        if pr_create.source_branch == pr_create.target_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and target branches must be different",
            )

        # Get next PR number for this project
        max_number_result = await self.db.execute(
            select(func.max(PullRequest.pr_number)).where(PullRequest.project_id == project_id)
        )
        max_number = max_number_result.scalar() or 0
        pr_number = max_number + 1

        # Create PR in database
        db_pr = PullRequest(
            project_id=project_id,
            pr_number=pr_number,
            title=pr_create.title,
            description=pr_create.description,
            source_branch=pr_create.source_branch,
            target_branch=pr_create.target_branch,
            author_id=user.id,
            author_name=user.name,
            author_email=user.email,
            status=PRStatus.OPEN.value,
        )
        self.db.add(db_pr)
        await self.db.flush()

        # Sync with GitHub if integration exists and we can resolve a token
        gh_result = await self._get_github_token(project_id)
        if gh_result:
            github_integration, token = gh_result
            try:
                gh_pr = await self.github_service.create_pull_request(
                    token=token,
                    owner=github_integration.repo_owner,
                    repo=github_integration.repo_name,
                    title=pr_create.title,
                    head=pr_create.source_branch,
                    base=pr_create.target_branch,
                    body=pr_create.description,
                )
                db_pr.github_pr_number = gh_pr.number
                db_pr.github_pr_url = gh_pr.html_url
            except Exception as e:
                logger.warning(f"Failed to create GitHub PR: {e}")

        await self.db.commit()
        await self.db.refresh(db_pr, ["reviews", "comments"])

        # Notify project owners/admins about the new PR
        notif = NotificationService(self.db)
        await notif.notify_project_roles(
            project_id=project_id,
            project_name=project.name,
            roles=["owner", "admin"],
            notification_type="pr_opened",
            title=f"PR #{pr_number}: {pr_create.title}",
            body=pr_create.description[:200] if pr_create.description else None,
            target_id=str(db_pr.id),
            exclude_user_id=user.id,
        )
        await self.db.commit()

        return await self._to_pr_response(db_pr, project_id)

    async def list_pull_requests(
        self,
        project_id: UUID,
        user: CurrentUser | None,
        status_filter: str | None = None,
        author_id: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> PRListResponse:
        """List pull requests for a project."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        # Sync merge commits from git history to PR records
        await self._sync_merge_commits_to_prs(project_id)

        # Build query
        query = (
            select(PullRequest)
            .options(selectinload(PullRequest.reviews))
            .options(selectinload(PullRequest.comments))
            .where(PullRequest.project_id == project_id)
        )

        if status_filter:
            query = query.where(PullRequest.status == status_filter)

        if author_id:
            query = query.where(PullRequest.author_id == author_id)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # Apply pagination and ordering
        query = query.order_by(PullRequest.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        prs = result.scalars().all()

        items = [await self._to_pr_response(pr, project_id) for pr in prs]

        return PRListResponse(items=items, total=total, skip=skip, limit=limit)

    async def get_pull_request(
        self, project_id: UUID, pr_number: int, user: CurrentUser | None
    ) -> PRResponse:
        """Get a pull request by number."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        pr = await self._get_pr(project_id, pr_number)
        return await self._to_pr_response(pr, project_id)

    async def update_pull_request(
        self, project_id: UUID, pr_number: int, pr_update: PRUpdate, user: CurrentUser
    ) -> PRResponse:
        """Update a pull request."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        # Only author, admin, or owner can update
        user_role = self._get_user_role(project, user)
        if user.id != pr.author_id and user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author or admins can update this pull request",
            )

        if pr.status != PRStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update a closed or merged pull request",
            )

        # Apply updates
        if pr_update.title is not None:
            pr.title = pr_update.title
        if pr_update.description is not None:
            pr.description = pr_update.description

        # Sync with GitHub if integration exists
        if pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    await self.github_service.update_pull_request(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                        title=pr_update.title,
                        body=pr_update.description,
                    )
                except Exception as e:
                    logger.warning(f"Failed to update GitHub PR: {e}")

        await self.db.commit()
        await self.db.refresh(pr)

        return await self._to_pr_response(pr, project_id)

    async def close_pull_request(
        self, project_id: UUID, pr_number: int, user: CurrentUser
    ) -> PRResponse:
        """Close a pull request without merging."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        # Only author, admin, or owner can close
        user_role = self._get_user_role(project, user)
        if user.id != pr.author_id and user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author or admins can close this pull request",
            )

        if pr.status != PRStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pull request is already closed or merged",
            )

        pr.status = PRStatus.CLOSED.value

        # Sync with GitHub if integration exists
        if pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    await self.github_service.close_pull_request(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                    )
                except Exception as e:
                    logger.warning(f"Failed to close GitHub PR: {e}")

        await self.db.commit()
        await self.db.refresh(pr)

        return await self._to_pr_response(pr, project_id)

    async def reopen_pull_request(
        self, project_id: UUID, pr_number: int, user: CurrentUser
    ) -> PRResponse:
        """Reopen a closed pull request."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        # Only author, admin, or owner can reopen
        user_role = self._get_user_role(project, user)
        if user.id != pr.author_id and user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author or admins can reopen this pull request",
            )

        if pr.status != PRStatus.CLOSED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only closed pull requests can be reopened",
            )

        pr.status = PRStatus.OPEN.value

        # Sync with GitHub if integration exists
        if pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    await self.github_service.reopen_pull_request(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                    )
                except Exception as e:
                    logger.warning(f"Failed to reopen GitHub PR: {e}")

        await self.db.commit()
        await self.db.refresh(pr)

        return await self._to_pr_response(pr, project_id)

    async def merge_pull_request(
        self,
        project_id: UUID,
        pr_number: int,
        merge_request: PRMergeRequest,
        user: CurrentUser,
    ) -> PRMergeResponse:
        """Merge a pull request."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        # Only admin or owner can merge
        user_role = self._get_user_role(project, user)
        if user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can merge pull requests",
            )

        if pr.status != PRStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pull request is not open",
            )

        # Check approval requirements
        approval_count = sum(1 for r in pr.reviews if r.status == ReviewStatus.APPROVED.value)
        if approval_count < project.pr_approval_required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pull request requires {project.pr_approval_required} approvals, but has {approval_count}",
            )

        # Capture commit hashes before merge
        branches = self.git_service.list_branches(project_id)
        branch_map = {b.name: b for b in branches}

        base_commit_hash = None
        head_commit_hash = None
        if pr.target_branch in branch_map:
            base_commit_hash = branch_map[pr.target_branch].commit_hash
        if pr.source_branch in branch_map:
            head_commit_hash = branch_map[pr.source_branch].commit_hash

        # Perform merge in local git
        merge_message = (
            merge_request.merge_message or f"Merge pull request #{pr_number}: {pr.title}"
        )
        merge_result = self.git_service.merge_branch(
            project_id=project_id,
            source=pr.source_branch,
            target=pr.target_branch,
            message=merge_message,
            author_name=user.name,
            author_email=user.email,
        )

        if not merge_result.success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Merge failed: {merge_result.message}",
            )

        # Update PR status and store commit hashes
        pr.status = PRStatus.MERGED.value
        pr.merged_by = user.id
        pr.merged_at = datetime.now(UTC)
        pr.merge_commit_hash = merge_result.merge_commit_hash
        pr.base_commit_hash = base_commit_hash
        pr.head_commit_hash = head_commit_hash

        # Delete source branch if requested
        if merge_request.delete_source_branch:
            try:
                self.git_service.delete_branch(project_id, pr.source_branch)
                # Clean up branch metadata
                await self.db.execute(
                    sa_delete(BranchMetadata).where(
                        BranchMetadata.project_id == project_id,
                        BranchMetadata.branch_name == pr.source_branch,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to delete source branch: {e}")

        # Sync with GitHub if integration exists
        if pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    await self.github_service.merge_pull_request(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                        commit_title=merge_message,
                    )
                except Exception as e:
                    logger.warning(f"Failed to merge GitHub PR: {e}")

        await self.db.commit()

        # Notify PR author that their PR was merged
        if pr.author_id != user.id:
            notif = NotificationService(self.db)
            await notif.create_notification(
                user_id=pr.author_id,
                notification_type="pr_merged",
                title=f"PR #{pr_number}: {pr.title} was merged",
                project_id=project_id,
                project_name=project.name,
                target_id=str(pr.id),
            )
            await self.db.commit()

        return PRMergeResponse(
            success=True,
            message="Pull request merged successfully",
            merged_at=pr.merged_at,
            merge_commit_hash=merge_result.merge_commit_hash,
        )

    # Reviews

    async def create_review(
        self, project_id: UUID, pr_number: int, review_create: ReviewCreate, user: CurrentUser
    ) -> ReviewResponse:
        """Create a review on a pull request."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        # Only admin or owner can approve or request changes
        user_role = self._get_user_role(project, user)
        if review_create.status in ("approved", "changes_requested") and user_role not in (
            "owner",
            "admin",
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can approve or request changes",
            )

        if pr.status != PRStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot review a closed or merged pull request",
            )

        # Create review
        db_review = PullRequestReview(
            pull_request_id=pr.id,
            reviewer_id=user.id,
            status=review_create.status,
            body=review_create.body,
        )
        self.db.add(db_review)

        # Sync with GitHub if integration exists
        if pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    # Map status to GitHub event
                    event_map = {
                        "approved": "APPROVE",
                        "changes_requested": "REQUEST_CHANGES",
                        "commented": "COMMENT",
                    }
                    gh_review = await self.github_service.create_review(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                        event=event_map.get(review_create.status, "COMMENT"),
                        body=review_create.body,
                    )
                    db_review.github_review_id = gh_review.id
                except Exception as e:
                    logger.warning(f"Failed to create GitHub review: {e}")

        await self.db.commit()
        await self.db.refresh(db_review)

        # Notify PR author about the review
        if pr.author_id != user.id:
            status_label = {
                "approved": "approved",
                "changes_requested": "requested changes on",
                "commented": "commented on",
            }.get(review_create.status, "reviewed")
            notif = NotificationService(self.db)
            await notif.create_notification(
                user_id=pr.author_id,
                notification_type="pr_review",
                title=f"{user.name or user.id} {status_label} PR #{pr_number}: {pr.title}",
                body=review_create.body[:200] if review_create.body else None,
                project_id=project_id,
                project_name=project.name,
                target_id=str(pr.id),
            )
            await self.db.commit()

        return self._to_review_response(db_review)

    async def list_reviews(
        self, project_id: UUID, pr_number: int, user: CurrentUser | None
    ) -> ReviewListResponse:
        """List reviews for a pull request."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        pr = await self._get_pr(project_id, pr_number)

        items = [self._to_review_response(r) for r in pr.reviews]
        return ReviewListResponse(items=items, total=len(items))

    # Comments

    async def create_comment(
        self, project_id: UUID, pr_number: int, comment_create: CommentCreate, user: CurrentUser
    ) -> CommentResponse:
        """Create a comment on a pull request."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        # Validate parent comment if provided
        if comment_create.parent_id:
            parent_result = await self.db.execute(
                select(PullRequestComment).where(
                    PullRequestComment.id == comment_create.parent_id,
                    PullRequestComment.pull_request_id == pr.id,
                )
            )
            if not parent_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent comment not found",
                )

        # Create comment
        db_comment = PullRequestComment(
            pull_request_id=pr.id,
            author_id=user.id,
            author_name=user.name,
            author_email=user.email,
            body=comment_create.body,
            parent_id=comment_create.parent_id,
        )
        self.db.add(db_comment)

        # Sync with GitHub if integration exists (only for top-level comments)
        if not comment_create.parent_id and pr.github_pr_number:
            gh_result = await self._get_github_token(project_id)
            if gh_result:
                github_integration, token = gh_result
                try:
                    gh_comment = await self.github_service.create_comment(
                        token=token,
                        owner=github_integration.repo_owner,
                        repo=github_integration.repo_name,
                        pr_number=pr.github_pr_number,
                        body=comment_create.body,
                    )
                    db_comment.github_comment_id = gh_comment.id
                except Exception as e:
                    logger.warning(f"Failed to create GitHub comment: {e}")

        await self.db.commit()
        await self.db.refresh(db_comment, ["replies"])

        return self._to_comment_response(db_comment)

    async def list_comments(
        self, project_id: UUID, pr_number: int, user: CurrentUser | None
    ) -> CommentListResponse:
        """List comments for a pull request."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        pr = await self._get_pr(project_id, pr_number)

        # Get top-level comments only (not replies)
        result = await self.db.execute(
            select(PullRequestComment)
            .options(selectinload(PullRequestComment.replies))
            .where(
                PullRequestComment.pull_request_id == pr.id,
                PullRequestComment.parent_id.is_(None),
            )
            .order_by(PullRequestComment.created_at.asc())
        )
        comments = result.scalars().all()

        items = [self._to_comment_response(c) for c in comments]
        return CommentListResponse(items=items, total=len(items))

    async def update_comment(
        self,
        project_id: UUID,
        pr_number: int,
        comment_id: UUID,
        comment_update: CommentUpdate,
        user: CurrentUser,
    ) -> CommentResponse:
        """Update a comment."""
        await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        result = await self.db.execute(
            select(PullRequestComment)
            .options(selectinload(PullRequestComment.replies))
            .where(
                PullRequestComment.id == comment_id,
                PullRequestComment.pull_request_id == pr.id,
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )

        # Only author can update their comment
        if comment.author_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own comments",
            )

        comment.body = comment_update.body
        await self.db.commit()
        await self.db.refresh(comment)

        return self._to_comment_response(comment)

    async def delete_comment(
        self, project_id: UUID, pr_number: int, comment_id: UUID, user: CurrentUser
    ) -> None:
        """Delete a comment."""
        project = await self._get_project(project_id)
        pr = await self._get_pr(project_id, pr_number)

        result = await self.db.execute(
            select(PullRequestComment).where(
                PullRequestComment.id == comment_id,
                PullRequestComment.pull_request_id == pr.id,
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )

        # Only author, admin, or owner can delete
        user_role = self._get_user_role(project, user)
        if comment.author_id != user.id and user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own comments",
            )

        await self.db.delete(comment)
        await self.db.commit()

    # Branches

    async def list_branches(self, project_id: UUID, user: CurrentUser | None) -> BranchListResponse:
        """List branches for a project."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        branches = self.git_service.list_branches(project_id)
        current = self.git_service.get_current_branch(project_id)
        default = self.git_service.get_default_branch(project_id)

        items = [
            BranchInfo(
                name=b.name,
                is_current=b.is_current,
                is_default=b.is_default,
                commit_hash=b.commit_hash,
                commit_message=b.commit_message,
                commit_date=b.commit_date,
                commits_ahead=b.commits_ahead,
                commits_behind=b.commits_behind,
            )
            for b in branches
        ]

        return BranchListResponse(
            items=items,
            current_branch=current,
            default_branch=default,
        )

    async def create_branch(
        self, project_id: UUID, branch_create: BranchCreate, user: CurrentUser
    ) -> BranchInfo:
        """Create a new branch."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin", "editor"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only editors and above can create branches",
            )

        from_branch = branch_create.from_branch or self.git_service.get_current_branch(project_id)

        try:
            branch_info = self.git_service.create_branch(
                project_id, branch_create.name, from_branch
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

        return BranchInfo(
            name=branch_info.name,
            is_current=branch_info.is_current,
            is_default=branch_info.is_default,
            commit_hash=branch_info.commit_hash,
            commit_message=branch_info.commit_message,
            commit_date=branch_info.commit_date,
            commits_ahead=branch_info.commits_ahead,
            commits_behind=branch_info.commits_behind,
        )

    async def switch_branch(
        self, project_id: UUID, branch_name: str, user: CurrentUser
    ) -> BranchInfo:
        """Switch to a different branch."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin", "editor"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only editors and above can switch branches",
            )

        try:
            branch_info = self.git_service.switch_branch(project_id, branch_name)
        except KeyError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Branch '{branch_name}' not found",
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

        return BranchInfo(
            name=branch_info.name,
            is_current=branch_info.is_current,
            is_default=branch_info.is_default,
            commit_hash=branch_info.commit_hash,
            commit_message=branch_info.commit_message,
            commit_date=branch_info.commit_date,
            commits_ahead=branch_info.commits_ahead,
            commits_behind=branch_info.commits_behind,
        )

    # PR Commits and Diff

    async def get_pr_commits(
        self, project_id: UUID, pr_number: int, user: CurrentUser | None
    ) -> PRCommitListResponse:
        """Get commits for a pull request."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        pr = await self._get_pr(project_id, pr_number)

        # For merged PRs with stored commit hashes, use those
        # Otherwise fall back to branch names (for open PRs)
        if pr.status == PRStatus.MERGED.value and pr.base_commit_hash and pr.head_commit_hash:
            from_ref = pr.base_commit_hash
            to_ref = pr.head_commit_hash
        else:
            from_ref = pr.target_branch
            to_ref = pr.source_branch

        # Get commits between target and source
        try:
            commits = self.git_service.get_commits_between(project_id, from_ref, to_ref)
        except ValueError:
            # If we can't get commits (e.g., branch deleted, no stored hashes)
            commits = []

        items = [
            PRCommit(
                hash=c.hash,
                short_hash=c.short_hash,
                message=c.message,
                author_name=c.author_name,
                author_email=c.author_email,
                timestamp=datetime.fromisoformat(c.timestamp),
            )
            for c in commits
        ]

        return PRCommitListResponse(items=items, total=len(items))

    async def get_pr_diff(
        self, project_id: UUID, pr_number: int, user: CurrentUser | None
    ) -> PRDiffResponse:
        """Get diff for a pull request."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        pr = await self._get_pr(project_id, pr_number)

        # For merged PRs with stored commit hashes, use those
        # Otherwise fall back to branch names (for open PRs)
        if pr.status == PRStatus.MERGED.value and pr.base_commit_hash and pr.head_commit_hash:
            from_ref = pr.base_commit_hash
            to_ref = pr.head_commit_hash
        else:
            from_ref = pr.target_branch
            to_ref = pr.source_branch

        # Get diff between target and source
        try:
            diff_info = self.git_service.diff_versions(project_id, from_ref, to_ref)
        except ValueError as e:
            # Branch may have been deleted after merge without stored hashes
            if pr.status == PRStatus.MERGED.value:
                # Return empty diff for merged PRs with deleted branches
                return PRDiffResponse(
                    files=[],
                    total_additions=0,
                    total_deletions=0,
                    files_changed=0,
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot compute diff: {e}",
            ) from e

        # Map change types
        change_type_map = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
        }

        files = []
        for change in diff_info.changes:
            change_type = change_type_map.get(change.change_type, "modified")
            files.append(
                PRFileChange(
                    path=change.path,
                    change_type=change_type,  # type: ignore
                    old_path=change.old_path,
                    additions=change.additions,
                    deletions=change.deletions,
                    patch=change.patch,
                )
            )

        return PRDiffResponse(
            files=files,
            total_additions=diff_info.total_additions,
            total_deletions=diff_info.total_deletions,
            files_changed=diff_info.files_changed,
        )

    # GitHub Integration

    async def get_github_integration(
        self, project_id: UUID, user: CurrentUser
    ) -> GitHubIntegrationResponse | None:
        """Get GitHub integration for a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can view GitHub integration",
            )

        integration = await self._get_github_integration(project_id)
        if not integration:
            return None

        return self._to_github_integration_response(integration)

    async def _sync_remote_config_for_webhooks(
        self,
        project_id: UUID,
        integration: GitHubIntegration,
        webhooks_enabled: bool,
    ) -> None:
        """Create or update RemoteSyncConfig when webhook state changes."""
        result = await self.db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_id)
        )
        sync_config = result.scalar_one_or_none()

        if webhooks_enabled:
            if sync_config is None:
                sync_config = RemoteSyncConfig(
                    project_id=project_id,
                    repo_owner=integration.repo_owner,
                    repo_name=integration.repo_name,
                    branch=integration.default_branch or "main",
                    file_path=integration.ontology_file_path or "",
                    frequency="webhook",
                    enabled=True,
                    update_mode="review_required",
                )
                self.db.add(sync_config)
            else:
                sync_config.frequency = "webhook"
                sync_config.enabled = True
        else:
            if sync_config is not None and sync_config.frequency == "webhook":
                sync_config.frequency = "manual"

    async def create_github_integration(
        self,
        project_id: UUID,
        integration_create: GitHubIntegrationCreate,
        user: CurrentUser,
    ) -> GitHubIntegrationResponse:
        """Create GitHub integration for a project."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can setup GitHub integration",
            )

        # Check if integration already exists
        existing = await self._get_github_integration(project_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub integration already exists. Delete it first to reconfigure.",
            )

        # Generate webhook secret only if webhooks are enabled
        webhook_secret = secrets.token_urlsafe(32) if integration_create.webhooks_enabled else None

        # Create integration
        db_integration = GitHubIntegration(
            project_id=project_id,
            repo_owner=integration_create.repo_owner,
            repo_name=integration_create.repo_name,
            installation_id=None,
            webhook_secret=webhook_secret,
            connected_by_user_id=user.id,
            webhooks_enabled=integration_create.webhooks_enabled,
            default_branch=integration_create.default_branch,
            ontology_file_path=integration_create.ontology_file_path,
            turtle_file_path=integration_create.turtle_file_path,
        )
        self.db.add(db_integration)

        # Setup remote in git repository
        remote_url = (
            f"https://github.com/{integration_create.repo_owner}/{integration_create.repo_name}.git"
        )
        self.git_service.setup_remote(project_id, remote_url)

        # Auto-create remote sync config when webhooks are enabled
        if integration_create.webhooks_enabled:
            await self._sync_remote_config_for_webhooks(
                project_id, db_integration, webhooks_enabled=True
            )

        await self.db.commit()
        await self.db.refresh(db_integration)

        return self._to_github_integration_response(db_integration)

    async def update_github_integration(
        self,
        project_id: UUID,
        integration_update: GitHubIntegrationUpdate,
        user: CurrentUser,
    ) -> GitHubIntegrationResponse:
        """Update GitHub integration settings."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can update GitHub integration",
            )

        integration = await self._get_github_integration(project_id)
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub integration not found",
            )

        if integration_update.default_branch is not None:
            integration.default_branch = integration_update.default_branch
        if integration_update.sync_enabled is not None:
            integration.sync_enabled = integration_update.sync_enabled
        if integration_update.webhooks_enabled is not None:
            integration.webhooks_enabled = integration_update.webhooks_enabled
            # Generate webhook secret if enabling webhooks and none exists
            if integration_update.webhooks_enabled and not integration.webhook_secret:
                integration.webhook_secret = secrets.token_urlsafe(32)
            # Clear hook ID when disabling webhooks
            if not integration_update.webhooks_enabled:
                integration.github_hook_id = None

            # Auto-create/update remote sync config
            await self._sync_remote_config_for_webhooks(
                project_id, integration, integration_update.webhooks_enabled
            )

        await self.db.commit()
        await self.db.refresh(integration)

        return self._to_github_integration_response(integration)

    async def get_webhook_secret(
        self, project_id: UUID, user: CurrentUser
    ) -> dict[str, str | None]:
        """Retrieve the webhook secret for a project's GitHub integration."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can view the webhook secret",
            )

        integration = await self._get_github_integration(project_id)
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub integration not found",
            )

        if not integration.webhooks_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhooks are not enabled for this integration",
            )

        return {
            "webhook_secret": integration.webhook_secret,
            "webhook_url": f"/api/v1/webhooks/github/{project_id}",
        }

    async def setup_or_detect_webhook(self, project_id: UUID, user: CurrentUser) -> dict[str, Any]:
        """Auto-detect or auto-create a GitHub webhook for the project.

        Returns a dict with status, github_hook_id, and message.
        """
        from ontokit.core.config import settings

        project = await self._get_project(project_id)
        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can setup webhooks",
            )

        integration = await self._get_github_integration(project_id)
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub integration not found",
            )

        if not integration.webhooks_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhooks are not enabled",
            )

        # Get user's PAT
        result = await self.db.execute(
            select(UserGitHubToken).where(UserGitHubToken.user_id == user.id)
        )
        token_record = result.scalar_one_or_none()
        if not token_record:
            return {
                "status": "no_token",
                "github_hook_id": None,
                "message": "No GitHub token configured. Connect your GitHub account in Settings.",
            }

        pat = decrypt_token(token_record.encrypted_token)
        scopes = token_record.token_scopes or ""

        webhook_url = f"{settings.api_base_url}/api/v1/projects/webhooks/github/{project_id}"

        # Try to detect existing hook
        if self.github_service.has_hook_read_scope(scopes):
            try:
                existing = await self.github_service.find_hook_by_url(
                    pat, integration.repo_owner, integration.repo_name, webhook_url
                )
                if existing:
                    hook_id = existing.get("id")
                    integration.github_hook_id = hook_id
                    await self.db.commit()
                    return {
                        "status": "configured",
                        "github_hook_id": hook_id,
                        "message": "Existing webhook detected on GitHub.",
                    }
            except Exception:
                logger.warning("Failed to list hooks on GitHub", exc_info=True)

            # Try to create if we have write scope
            if self.github_service.has_hook_write_scope(scopes):
                # GitHub rejects localhost URLs — can't auto-create in dev
                if "localhost" in webhook_url or "127.0.0.1" in webhook_url:
                    return {
                        "status": "manual_required",
                        "github_hook_id": None,
                        "message": "Cannot auto-create webhooks with a localhost URL. "
                        "Set API_BASE_URL to a publicly reachable address, "
                        "or configure the webhook manually on GitHub.",
                    }

                if not integration.webhook_secret:
                    integration.webhook_secret = secrets.token_urlsafe(32)

                try:
                    created = await self.github_service.create_repo_hook(
                        pat,
                        integration.repo_owner,
                        integration.repo_name,
                        webhook_url,
                        integration.webhook_secret,
                    )
                    hook_id = created.get("id")
                    integration.github_hook_id = hook_id
                    await self.db.commit()
                    return {
                        "status": "created",
                        "github_hook_id": hook_id,
                        "message": "Webhook auto-created on GitHub.",
                    }
                except Exception as exc:
                    logger.warning("Failed to create hook on GitHub: %s", exc, exc_info=True)
                    return {
                        "status": "error",
                        "github_hook_id": None,
                        "message": f"Failed to create webhook on GitHub: {exc}",
                    }

            # Has read but not write
            return {
                "status": "manual_required",
                "github_hook_id": None,
                "message": "Your token can read hooks but not create them. "
                "Add the admin:repo_hook scope or configure the webhook manually.",
            }

        # No hook scopes at all
        return {
            "status": "no_scope",
            "github_hook_id": None,
            "message": "Your token lacks the admin:repo_hook scope. "
            "Add it to auto-configure webhooks, or set up the webhook manually.",
        }

    async def delete_github_integration(self, project_id: UUID, user: CurrentUser) -> None:
        """Delete GitHub integration for a project."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can delete GitHub integration",
            )

        integration = await self._get_github_integration(project_id)
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitHub integration not found",
            )

        await self.db.delete(integration)
        await self.db.commit()

    # PR Settings

    async def get_pr_settings(self, project_id: UUID, user: CurrentUser) -> PRSettingsResponse:
        """Get PR workflow settings for a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can view PR settings",
            )

        integration = await self._get_github_integration(project_id)
        github_resp = self._to_github_integration_response(integration) if integration else None

        return PRSettingsResponse(
            pr_approval_required=project.pr_approval_required,
            github_integration=github_resp,
        )

    async def update_pr_settings(
        self,
        project_id: UUID,
        settings_update: PRSettingsUpdate,
        user: CurrentUser,
    ) -> PRSettingsResponse:
        """Update PR workflow settings for a project."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can update PR settings",
            )

        project.pr_approval_required = settings_update.pr_approval_required

        await self.db.commit()
        await self.db.refresh(project)

        integration = await self._get_github_integration(project_id)
        github_resp = self._to_github_integration_response(integration) if integration else None

        return PRSettingsResponse(
            pr_approval_required=project.pr_approval_required,
            github_integration=github_resp,
        )

    # Webhook Handlers

    async def handle_github_pr_webhook(
        self, project_id: UUID, action: str, pr_data: dict[str, Any]
    ) -> None:
        """Handle GitHub pull_request webhook events."""
        integration = await self._get_github_integration(project_id)
        if not integration or not integration.sync_enabled:
            return

        github_pr_number = pr_data["number"]

        # Find local PR by GitHub PR number
        result = await self.db.execute(
            select(PullRequest).where(
                PullRequest.project_id == project_id,
                PullRequest.github_pr_number == github_pr_number,
            )
        )
        pr = result.scalar_one_or_none()

        if action == "closed":
            if pr:
                if pr_data.get("merged"):
                    pr.status = PRStatus.MERGED.value
                    pr.merged_at = datetime.now(UTC)
                else:
                    pr.status = PRStatus.CLOSED.value
                await self.db.commit()

        elif action == "reopened":
            if pr:
                pr.status = PRStatus.OPEN.value
                await self.db.commit()

        elif action == "edited" and pr:
            pr.title = pr_data["title"]
            pr.description = pr_data.get("body")
            await self.db.commit()

    async def handle_github_review_webhook(
        self, project_id: UUID, action: str, review_data: dict[str, Any], pr_data: dict[str, Any]
    ) -> None:
        """Handle GitHub pull_request_review webhook events."""
        if action != "submitted":
            return

        integration = await self._get_github_integration(project_id)
        if not integration or not integration.sync_enabled:
            return

        github_pr_number = pr_data["number"]
        github_review_id = review_data["id"]

        # Find local PR
        result = await self.db.execute(
            select(PullRequest).where(
                PullRequest.project_id == project_id,
                PullRequest.github_pr_number == github_pr_number,
            )
        )
        pr = result.scalar_one_or_none()
        if not pr:
            return

        # Check if review already exists
        existing = await self.db.execute(
            select(PullRequestReview).where(PullRequestReview.github_review_id == github_review_id)
        )
        if existing.scalar_one_or_none():
            return

        # Map GitHub state to our status
        state_map = {
            "APPROVED": ReviewStatus.APPROVED.value,
            "CHANGES_REQUESTED": ReviewStatus.CHANGES_REQUESTED.value,
            "COMMENTED": ReviewStatus.COMMENTED.value,
        }
        status_value = state_map.get(review_data["state"], ReviewStatus.COMMENTED.value)

        # Create review (we don't have the user ID from GitHub, use login as placeholder)
        db_review = PullRequestReview(
            pull_request_id=pr.id,
            reviewer_id=f"github:{review_data['user']['login']}",
            status=status_value,
            body=review_data.get("body"),
            github_review_id=github_review_id,
        )
        self.db.add(db_review)
        await self.db.commit()

    async def handle_github_push_webhook(
        self,
        project_id: UUID,
        ref: str,
        commits: list[dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Handle GitHub push webhook events."""
        integration = await self._get_github_integration(project_id)
        if not integration or not integration.sync_enabled:
            return

        # Only sync pushes to main branch
        if ref != f"refs/heads/{integration.default_branch}":
            return

        # Pull latest changes
        try:
            # TODO: implement pull_branch on BareGitRepositoryService
            self.git_service.pull_branch(project_id, integration.default_branch, "origin")  # type: ignore[attr-defined]
            integration.last_sync_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to pull from GitHub: {e}")

    # Open PR Summary (for notification bell)

    async def get_open_pr_summary(self, user: CurrentUser) -> OpenPRsSummary:
        """Get a summary of open PRs across projects the user manages."""
        if user.is_superadmin:
            query = (
                select(
                    PullRequest.project_id,
                    Project.name.label("project_name"),
                    func.count().label("open_count"),
                )
                .join(Project, PullRequest.project_id == Project.id)
                .where(PullRequest.status == PRStatus.OPEN.value)
                .group_by(PullRequest.project_id, Project.name)
            )
        else:
            query = (
                select(
                    PullRequest.project_id,
                    Project.name.label("project_name"),
                    func.count().label("open_count"),
                )
                .join(Project, PullRequest.project_id == Project.id)
                .join(
                    ProjectMember,
                    (ProjectMember.project_id == PullRequest.project_id)
                    & (ProjectMember.user_id == user.id)
                    & (ProjectMember.role.in_(["owner", "admin"])),
                )
                .where(PullRequest.status == PRStatus.OPEN.value)
                .group_by(PullRequest.project_id, Project.name)
            )

        result = await self.db.execute(query)
        rows = result.all()

        by_project = [
            ProjectOpenPRCount(
                project_id=row.project_id,
                project_name=row.project_name,
                open_count=row.open_count,
            )
            for row in rows
        ]

        total_open = sum(p.open_count for p in by_project)

        return OpenPRsSummary(total_open=total_open, by_project=by_project)

    # Helper methods

    async def _get_project(self, project_id: UUID) -> Project:
        """Get a project by ID or raise 404."""
        result = await self.db.execute(
            select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        return project

    async def _get_pr(self, project_id: UUID, pr_number: int) -> PullRequest:
        """Get a pull request by project ID and PR number or raise 404."""
        result = await self.db.execute(
            select(PullRequest)
            .options(selectinload(PullRequest.reviews))
            .options(selectinload(PullRequest.comments))
            .where(
                PullRequest.project_id == project_id,
                PullRequest.pr_number == pr_number,
            )
        )
        pr = result.scalar_one_or_none()

        if pr is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pull request not found",
            )

        return pr

    async def _get_github_integration(self, project_id: UUID) -> GitHubIntegration | None:
        """Get GitHub integration for a project."""
        result = await self.db.execute(
            select(GitHubIntegration).where(GitHubIntegration.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def _get_github_token(self, project_id: UUID) -> tuple[GitHubIntegration, str] | None:
        """Resolve a PAT for GitHub API calls on this project.

        Looks up integration -> connected_by_user_id -> UserGitHubToken -> decrypt.
        Returns None if any link is missing (graceful degradation).
        """
        integration = await self._get_github_integration(project_id)
        if not integration or not integration.sync_enabled:
            return None
        if not integration.connected_by_user_id:
            return None
        result = await self.db.execute(
            select(UserGitHubToken).where(
                UserGitHubToken.user_id == integration.connected_by_user_id
            )
        )
        token_row = result.scalar_one_or_none()
        if not token_row:
            return None
        try:
            token = decrypt_token(token_row.encrypted_token)
        except Exception:
            logger.warning(
                "Failed to decrypt GitHub token for user %s", integration.connected_by_user_id
            )
            return None
        return integration, token

    def _can_view(self, project: Project, user: CurrentUser | None) -> bool:
        """Check if user can view the project."""
        if project.is_public:
            return True

        if user is None:
            return False

        return any(m.user_id == user.id for m in project.members)

    def _get_user_role(self, project: Project, user: CurrentUser) -> ProjectRole | None:
        """Get user's role in the project."""
        for member in project.members:
            if member.user_id == user.id:
                return member.role  # type: ignore[return-value]
        return None

    async def _to_pr_response(self, pr: PullRequest, project_id: UUID) -> PRResponse:
        """Convert PullRequest model to response schema."""
        # Count reviews and approvals
        review_count = len(pr.reviews)
        approval_count = sum(1 for r in pr.reviews if r.status == ReviewStatus.APPROVED.value)
        comment_count = len(pr.comments)

        # Get commits ahead
        commits_ahead = 0
        try:
            commits = self.git_service.get_commits_between(
                project_id, pr.target_branch, pr.source_branch
            )
            commits_ahead = len(commits)
        except Exception:
            pass

        # Check if can merge
        project = await self._get_project(project_id)
        can_merge = (
            pr.status == PRStatus.OPEN.value and approval_count >= project.pr_approval_required
        )

        # Look up author info from Zitadel if missing
        author_name = pr.author_name
        author_email = pr.author_email
        if not author_name and pr.author_id:
            try:
                user_info = await self.user_service.get_user_info(pr.author_id)
                if user_info:
                    author_name = user_info.get("name")
                    author_email = user_info.get("email")
                    # Update the database record for future calls
                    if author_name or author_email:
                        if author_name:
                            pr.author_name = author_name
                        if author_email:
                            pr.author_email = author_email
                        await self.db.commit()
                        logger.info(f"Updated PR #{pr.pr_number} with author info from Zitadel")
            except Exception as e:
                logger.warning(f"Failed to look up user info for {pr.author_id}: {e}")

        return PRResponse(
            id=pr.id,
            project_id=pr.project_id,
            pr_number=pr.pr_number,
            title=pr.title,
            description=pr.description,
            source_branch=pr.source_branch,
            target_branch=pr.target_branch,
            status=pr.status,  # type: ignore
            author_id=pr.author_id,
            author=PRUser(id=pr.author_id, name=author_name, email=author_email),
            github_pr_number=pr.github_pr_number,
            github_pr_url=pr.github_pr_url,
            merged_by=pr.merged_by,
            merged_by_user=PRUser(id=pr.merged_by) if pr.merged_by else None,
            merged_at=pr.merged_at,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            review_count=review_count,
            approval_count=approval_count,
            comment_count=comment_count,
            commits_ahead=commits_ahead,
            can_merge=can_merge,
        )

    def _to_review_response(self, review: PullRequestReview) -> ReviewResponse:
        """Convert PullRequestReview model to response schema."""
        return ReviewResponse(
            id=review.id,
            pull_request_id=review.pull_request_id,
            reviewer_id=review.reviewer_id,
            reviewer=PRUser(id=review.reviewer_id),
            status=review.status,  # type: ignore
            body=review.body,
            github_review_id=review.github_review_id,
            created_at=review.created_at,
        )

    def _to_comment_response(self, comment: PullRequestComment) -> CommentResponse:
        """Convert PullRequestComment model to response schema."""
        replies = [self._to_comment_response(r) for r in comment.replies]

        return CommentResponse(
            id=comment.id,
            pull_request_id=comment.pull_request_id,
            author_id=comment.author_id,
            author=PRUser(
                id=comment.author_id,
                name=comment.author_name,
                email=comment.author_email,
            ),
            body=comment.body,
            parent_id=comment.parent_id,
            github_comment_id=comment.github_comment_id,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            replies=replies,
        )

    def _to_github_integration_response(
        self, integration: GitHubIntegration
    ) -> GitHubIntegrationResponse:
        """Convert GitHubIntegration model to response schema."""
        return GitHubIntegrationResponse(
            id=integration.id,
            project_id=integration.project_id,
            repo_owner=integration.repo_owner,
            repo_name=integration.repo_name,
            repo_url=f"https://github.com/{integration.repo_owner}/{integration.repo_name}",
            connected_by_user_id=integration.connected_by_user_id,
            webhooks_enabled=integration.webhooks_enabled,
            github_hook_id=integration.github_hook_id,
            default_branch=integration.default_branch,
            ontology_file_path=integration.ontology_file_path,
            turtle_file_path=integration.turtle_file_path,
            sync_enabled=integration.sync_enabled,
            last_sync_at=integration.last_sync_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
        )


def get_pull_request_service(db: AsyncSession) -> PullRequestService:
    """Factory function for dependency injection."""
    return PullRequestService(db)
