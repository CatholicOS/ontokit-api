"""Suggestion session service for managing suggester workflows."""

import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ontokit.core.auth import CurrentUser
from ontokit.core.beacon_token import create_beacon_token, verify_beacon_token
from ontokit.git import GitRepositoryService, get_git_service
from ontokit.models.project import Project
from ontokit.models.suggestion_session import SuggestionSession, SuggestionSessionStatus
from ontokit.schemas.pull_request import PRCreate
from ontokit.schemas.suggestion import (
    SuggestionBeaconRequest,
    SuggestionSaveRequest,
    SuggestionSaveResponse,
    SuggestionSessionListResponse,
    SuggestionSessionResponse,
    SuggestionSessionSummary,
    SuggestionSubmitRequest,
    SuggestionSubmitResponse,
)
from ontokit.services.pull_request_service import get_pull_request_service

logger = logging.getLogger(__name__)


class SuggestionService:
    """Service for suggestion session CRUD, save, submit, and auto-submit."""

    def __init__(
        self,
        db: AsyncSession,
        git_service: GitRepositoryService | None = None,
    ) -> None:
        self.db = db
        self.git_service = git_service or get_git_service()

    # --- Helpers ---

    async def _get_project(self, project_id: UUID) -> Project:
        """Get a project by ID with members loaded, or raise 404."""
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

    def _get_user_role(self, project: Project, user: CurrentUser) -> str | None:
        """Get user's role in the project."""
        for member in project.members:
            if member.user_id == user.id:
                return member.role
        return None

    def _can_suggest(self, role: str | None, user: CurrentUser) -> bool:
        """Check if the user's role allows suggesting."""
        if user.is_superadmin:
            return True
        return role in ("owner", "admin", "editor", "suggester")

    async def _verify_project_access(self, project_id: UUID, user: CurrentUser) -> None:
        """Verify the user still has suggest permissions on the project."""
        project = await self._get_project(project_id)
        role = self._get_user_role(project, user)
        if not self._can_suggest(role, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You no longer have permission to suggest changes",
            )

    def _get_git_ontology_path(self, project: Project) -> str:
        """Get the ontology file path within the git repo."""
        if project.source_file_path:
            return os.path.basename(project.source_file_path)
        return "ontology.ttl"

    async def _get_session(self, project_id: UUID, session_id: str) -> SuggestionSession:
        """Get a suggestion session or raise 404."""
        result = await self.db.execute(
            select(SuggestionSession).where(
                SuggestionSession.project_id == project_id,
                SuggestionSession.session_id == session_id,
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Suggestion session not found",
            )
        return session

    def _verify_ownership(self, session: SuggestionSession, user: CurrentUser) -> None:
        """Verify the user owns the session."""
        if session.user_id != user.id and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this suggestion session",
            )

    def _parse_entities_modified(self, session: SuggestionSession) -> list[str]:
        """Parse the JSON entities_modified field into a list."""
        if not session.entities_modified:
            return []
        try:
            return json.loads(session.entities_modified)
        except (json.JSONDecodeError, TypeError):
            return []

    def _update_entities_modified(self, session: SuggestionSession, label: str) -> None:
        """Add a label to the entities_modified list (deduplicated)."""
        entities = self._parse_entities_modified(session)
        if label not in entities:
            entities.append(label)
        session.entities_modified = json.dumps(entities)

    # --- Public methods ---

    async def create_session(
        self, project_id: UUID, user: CurrentUser
    ) -> SuggestionSessionResponse:
        """Create a new suggestion session with a dedicated branch."""
        project = await self._get_project(project_id)
        role = self._get_user_role(project, user)

        if not self._can_suggest(role, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to suggest changes",
            )

        # Check for existing active session
        result = await self.db.execute(
            select(SuggestionSession).where(
                SuggestionSession.project_id == project_id,
                SuggestionSession.user_id == user.id,
                SuggestionSession.status == SuggestionSessionStatus.ACTIVE.value,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return SuggestionSessionResponse(
                session_id=existing.session_id,
                branch=existing.branch,
                created_at=existing.created_at,
                beacon_token=existing.beacon_token,
            )

        # Generate identifiers
        session_id = f"s_{secrets.token_hex(8)}"
        user_prefix = user.id[:8]
        branch = f"suggest/{user_prefix}/{session_id}"
        beacon_token = create_beacon_token(session_id)

        # Create the git branch
        try:
            self.git_service.create_branch(project_id, branch)
        except Exception as e:
            logger.error(f"Failed to create suggestion branch: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create suggestion branch",
            ) from e

        # Create the database record
        db_session = SuggestionSession(
            project_id=project_id,
            user_id=user.id,
            user_name=user.name,
            user_email=user.email,
            session_id=session_id,
            branch=branch,
            beacon_token=beacon_token,
        )
        self.db.add(db_session)
        await self.db.commit()
        await self.db.refresh(db_session)

        return SuggestionSessionResponse(
            session_id=db_session.session_id,
            branch=db_session.branch,
            created_at=db_session.created_at,
            beacon_token=db_session.beacon_token,
        )

    async def save(
        self,
        project_id: UUID,
        session_id: str,
        data: SuggestionSaveRequest,
        user: CurrentUser,
    ) -> SuggestionSaveResponse:
        """Save content to the suggestion branch."""
        session = await self._get_session(project_id, session_id)
        self._verify_ownership(session, user)
        await self._verify_project_access(project_id, user)

        if session.status != SuggestionSessionStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is {session.status}, cannot save",
            )

        project = await self._get_project(project_id)
        filename = self._get_git_ontology_path(project)

        # Commit to the suggestion branch
        commit_message = f"Update {data.entity_label}"
        try:
            commit_info = self.git_service.commit_to_branch(
                project_id=project_id,
                branch_name=session.branch,
                ontology_content=data.content.encode("utf-8"),
                filename=filename,
                message=commit_message,
                author_name=session.user_name or "Suggester",
                author_email=session.user_email or "suggester@ontokit.dev",
            )
        except Exception as e:
            logger.error(f"Failed to save suggestion: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save suggestion to branch",
            ) from e

        # Update session metadata
        session.changes_count += 1
        self._update_entities_modified(session, data.entity_label)
        session.last_activity = datetime.now(UTC)
        await self.db.commit()

        return SuggestionSaveResponse(
            commit_hash=commit_info.hash,
            branch=session.branch,
            changes_count=session.changes_count,
        )

    async def submit(
        self,
        project_id: UUID,
        session_id: str,
        data: SuggestionSubmitRequest,
        user: CurrentUser,
    ) -> SuggestionSubmitResponse:
        """Submit the suggestion session by creating a PR."""
        session = await self._get_session(project_id, session_id)
        self._verify_ownership(session, user)
        await self._verify_project_access(project_id, user)

        if session.status != SuggestionSessionStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is {session.status}, cannot submit",
            )

        if session.changes_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No changes to submit",
            )

        return await self._create_pr_for_session(
            project_id, session, user, data.summary, "submitted"
        )

    async def _create_pr_for_session(
        self,
        project_id: UUID,
        session: SuggestionSession,
        user: CurrentUser,
        summary: str | None,
        new_status: str,
    ) -> SuggestionSubmitResponse:
        """Create a PR from a suggestion session."""
        entities = self._parse_entities_modified(session)
        entity_list = ", ".join(entities[:5])
        if len(entities) > 5:
            entity_list += f" (+{len(entities) - 5} more)"

        title = f"Suggestion: Update {entity_list}" if entities else "Suggestion"
        if len(title) > 500:
            title = title[:497] + "..."

        body_parts = []
        if summary:
            body_parts.append(summary)
        body_parts.append(f"\n**Entities modified** ({session.changes_count} changes):")
        for entity in entities:
            body_parts.append(f"- {entity}")
        body_parts.append(f"\n*Submitted by {session.user_name or session.user_id}*")
        description = "\n".join(body_parts)

        # Get default branch
        default_branch = self.git_service.get_default_branch(project_id)

        # Create PR via the existing PR service
        pr_service = get_pull_request_service(self.db)
        pr_create = PRCreate(
            title=title,
            description=description,
            source_branch=session.branch,
            target_branch=default_branch,
        )

        try:
            pr_response = await pr_service.create_pull_request(project_id, pr_create, user)
        except HTTPException as e:
            # If the user doesn't have editor role for PR creation,
            # fall back to creating the PR directly
            if e.status_code == status.HTTP_403_FORBIDDEN:
                pr_response = await self._create_pr_directly(project_id, pr_create, session)
            else:
                raise

        # Update session
        session.status = new_status
        session.pr_number = pr_response.pr_number
        session.pr_id = pr_response.id
        session.last_activity = datetime.now(UTC)
        await self.db.commit()

        return SuggestionSubmitResponse(
            pr_number=pr_response.pr_number,
            pr_url=pr_response.github_pr_url,
            status=new_status,
        )

    async def _create_pr_directly(
        self,
        project_id: UUID,
        pr_create: PRCreate,
        session: SuggestionSession,
    ):
        """Create a PR record directly when the user lacks editor role."""
        from sqlalchemy import func as sa_func

        from ontokit.models.pull_request import PRStatus, PullRequest

        max_retries = 3
        for attempt in range(max_retries):
            max_number_result = await self.db.execute(
                select(sa_func.max(PullRequest.pr_number)).where(
                    PullRequest.project_id == project_id
                )
            )
            max_number = max_number_result.scalar() or 0
            pr_number = max_number + 1

            db_pr = PullRequest(
                project_id=project_id,
                pr_number=pr_number,
                title=pr_create.title,
                description=pr_create.description,
                source_branch=pr_create.source_branch,
                target_branch=pr_create.target_branch,
                author_id=session.user_id,
                author_name=session.user_name,
                author_email=session.user_email,
                status=PRStatus.OPEN.value,
            )
            self.db.add(db_pr)
            try:
                await self.db.flush()
            except IntegrityError:
                await self.db.rollback()
                if attempt == max_retries - 1:
                    raise
                continue
            await self.db.refresh(db_pr)
            return db_pr

        # Unreachable, but satisfies type checker
        raise RuntimeError("Failed to allocate PR number")

    async def list_sessions(
        self, project_id: UUID, user: CurrentUser
    ) -> SuggestionSessionListResponse:
        """List suggestion sessions for the current user in a project."""
        result = await self.db.execute(
            select(SuggestionSession)
            .where(
                SuggestionSession.project_id == project_id,
                SuggestionSession.user_id == user.id,
            )
            .order_by(SuggestionSession.last_activity.desc())
        )
        sessions = result.scalars().all()

        items = []
        for s in sessions:
            # Resolve PR URL from pull_request relationship if available
            pr_url = None
            if s.pr_id:
                from ontokit.models.pull_request import PullRequest

                pr_result = await self.db.execute(
                    select(PullRequest).where(PullRequest.id == s.pr_id)
                )
                pr = pr_result.scalar_one_or_none()
                if pr:
                    pr_url = pr.github_pr_url if hasattr(pr, "github_pr_url") else None

            items.append(
                SuggestionSessionSummary(
                    session_id=s.session_id,
                    branch=s.branch,
                    changes_count=s.changes_count,
                    last_activity=s.last_activity,
                    entities_modified=self._parse_entities_modified(s),
                    status=s.status,
                    pr_number=s.pr_number,
                    pr_url=pr_url,
                )
            )

        return SuggestionSessionListResponse(items=items)

    async def discard(self, project_id: UUID, session_id: str, user: CurrentUser) -> None:
        """Discard a suggestion session and delete its branch."""
        session = await self._get_session(project_id, session_id)
        self._verify_ownership(session, user)

        if session.status != SuggestionSessionStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Session is {session.status}, cannot discard",
            )

        # Delete the git branch
        try:
            self.git_service.delete_branch(project_id, session.branch, force=True)
        except Exception as e:
            logger.warning(f"Failed to delete suggestion branch {session.branch}: {e}")

        session.status = SuggestionSessionStatus.DISCARDED.value
        session.last_activity = datetime.now(UTC)
        await self.db.commit()

    async def beacon_save(
        self, project_id: UUID, data: SuggestionBeaconRequest, token: str
    ) -> None:
        """Handle a beacon save (sendBeacon flush) with token-based auth."""
        # Verify the beacon token
        verified_session_id = verify_beacon_token(token)
        if verified_session_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired beacon token",
            )

        if verified_session_id != data.session_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token does not match session",
            )

        # Look up the session
        session = await self._get_session(project_id, data.session_id)

        if session.status != SuggestionSessionStatus.ACTIVE.value:
            return  # Silently ignore saves to non-active sessions

        # Re-check project access with the session owner's identity
        session_user = CurrentUser(
            id=session.user_id,
            email=session.user_email,
            name=session.user_name,
        )
        await self._verify_project_access(project_id, session_user)

        project = await self._get_project(project_id)
        filename = self._get_git_ontology_path(project)

        # Commit without full validation (speed over correctness for beacon)
        try:
            self.git_service.commit_to_branch(
                project_id=project_id,
                branch_name=session.branch,
                ontology_content=data.content.encode("utf-8"),
                filename=filename,
                message="Auto-save (beacon)",
                author_name=session.user_name or "Suggester",
                author_email=session.user_email or "suggester@ontokit.dev",
            )
        except Exception as e:
            logger.warning(f"Beacon save failed for session {data.session_id}: {e}")
            return  # Beacon is fire-and-forget

        session.changes_count += 1
        session.last_activity = datetime.now(UTC)
        await self.db.commit()

    async def auto_submit_stale_sessions(self) -> int:
        """Auto-create PRs for stale suggestion sessions.

        Returns the number of sessions auto-submitted.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=30)

        result = await self.db.execute(
            select(SuggestionSession).where(
                SuggestionSession.status == SuggestionSessionStatus.ACTIVE.value,
                SuggestionSession.changes_count > 0,
                SuggestionSession.last_activity < cutoff,
            )
        )
        stale_sessions = result.scalars().all()

        count = 0
        for session in stale_sessions:
            # Atomically claim the session to prevent concurrent workers from
            # processing the same session.  Only proceed if this UPDATE affects
            # exactly one row (i.e. no other worker claimed it first).
            claim_result = await self.db.execute(
                update(SuggestionSession)
                .where(
                    SuggestionSession.id == session.id,
                    SuggestionSession.status == SuggestionSessionStatus.ACTIVE.value,
                    SuggestionSession.changes_count > 0,
                    SuggestionSession.last_activity < cutoff,
                )
                .values(status=SuggestionSessionStatus.AUTO_SUBMITTED.value)
            )
            if claim_result.rowcount != 1:
                continue  # Another worker already claimed this session
            await self.db.commit()
            # Refresh so the in-memory object reflects the new status
            await self.db.refresh(session)

            mock_user = CurrentUser(
                id=session.user_id,
                email=session.user_email,
                name=session.user_name,
            )

            # Verify the user still has project access before auto-submitting
            try:
                await self._verify_project_access(session.project_id, mock_user)
            except HTTPException:
                session.status = SuggestionSessionStatus.DISCARDED.value
                await self.db.commit()
                logger.warning(
                    f"Discarded session {session.session_id}: "
                    f"user {session.user_id} lost project access"
                )
                continue

            try:
                await self._create_pr_for_session(
                    session.project_id,
                    session,
                    mock_user,
                    summary="Auto-submitted: session inactive for 30+ minutes.",
                    new_status=SuggestionSessionStatus.AUTO_SUBMITTED.value,
                )
                count += 1
                logger.info(
                    f"Auto-submitted suggestion session {session.session_id} "
                    f"for project {session.project_id}"
                )
            except Exception as e:
                # Rollback any failed transaction state before reverting the claim
                await self.db.rollback()
                session.status = SuggestionSessionStatus.ACTIVE.value
                await self.db.commit()
                logger.error(f"Failed to auto-submit session {session.session_id}: {e}")

        return count


def get_suggestion_service(db: AsyncSession) -> SuggestionService:
    """Factory function for dependency injection."""
    return SuggestionService(db)
