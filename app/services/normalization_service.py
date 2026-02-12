"""Normalization service for managing ontology normalization runs."""

import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.git import GitRepositoryService, get_git_service
from app.models.normalization import NormalizationRun
from app.models.project import Project
from app.services.ontology_extractor import OntologyMetadataExtractor
from app.services.storage import StorageError, StorageService

logger = logging.getLogger(__name__)


class NormalizationService:
    """Service for managing ontology normalization runs."""

    def __init__(
        self,
        db: AsyncSession,
        storage: StorageService,
        git_service: GitRepositoryService | None = None,
    ) -> None:
        self.db = db
        self.storage = storage
        self.git_service = git_service or get_git_service()
        self.extractor = OntologyMetadataExtractor()

    async def check_normalization_status(
        self, project: Project
    ) -> dict:
        """
        Check if a project's ontology needs normalization.

        Returns a status dict with:
        - needs_normalization: bool
        - last_run: datetime | None
        - report: NormalizationReport | None (preview of what would change)
        """
        if not project.source_file_path:
            return {
                "needs_normalization": False,
                "last_run": None,
                "report": None,
                "error": "Project has no ontology file",
            }

        # Get last normalization run
        result = await self.db.execute(
            select(NormalizationRun)
            .where(NormalizationRun.project_id == project.id)
            .where(NormalizationRun.is_dry_run == False)  # noqa: E712
            .order_by(NormalizationRun.created_at.desc())
            .limit(1)
        )
        last_run = result.scalar_one_or_none()

        try:
            # Download current content
            object_name = self._get_object_name(project.source_file_path)
            content = await self.storage.download_file(object_name)
            filename = Path(object_name).name

            # Check if normalization is needed
            needs_normalization, report = self.extractor.check_normalization_needed(
                content, filename
            )

            return {
                "needs_normalization": needs_normalization,
                "last_run": last_run.created_at if last_run else None,
                "last_run_id": str(last_run.id) if last_run else None,
                "report": report.to_dict() if report else None,
                "error": None,
            }

        except StorageError as e:
            logger.warning(f"Failed to check normalization for project {project.id}: {e}")
            return {
                "needs_normalization": False,
                "last_run": last_run.created_at if last_run else None,
                "last_run_id": str(last_run.id) if last_run else None,
                "report": None,
                "error": f"Storage error: {e}",
            }
        except Exception as e:
            logger.warning(f"Failed to check normalization for project {project.id}: {e}")
            return {
                "needs_normalization": False,
                "last_run": last_run.created_at if last_run else None,
                "last_run_id": str(last_run.id) if last_run else None,
                "report": None,
                "error": str(e),
            }

    async def run_normalization(
        self,
        project: Project,
        user: CurrentUser | None = None,
        trigger_type: str = "manual",
        dry_run: bool = False,
    ) -> NormalizationRun:
        """
        Run normalization on a project's ontology.

        Args:
            project: The project to normalize
            user: The user triggering the normalization (None for system)
            trigger_type: "import", "manual", or "automatic"
            dry_run: If True, don't commit changes, just record what would happen

        Returns:
            The NormalizationRun record
        """
        if not project.source_file_path:
            raise ValueError("Project has no ontology file")

        # Download current content
        object_name = self._get_object_name(project.source_file_path)
        content = await self.storage.download_file(object_name)
        filename = Path(object_name).name

        # Normalize
        normalized_content, report = self.extractor.normalize_to_turtle(content, filename)

        commit_hash = None
        content_changed = normalized_content != content

        if not dry_run and content_changed:
            # Upload normalized content
            await self.storage.upload_file(object_name, normalized_content, "text/turtle")

            # Commit to git
            if self.git_service.repository_exists(project.id):
                commit_message = (
                    "Normalize ontology to canonical Turtle format\n\n"
                    f"Trigger: {trigger_type}\n"
                    f"Triple count: {report.triple_count}\n"
                )
                if report.prefixes_removed:
                    commit_message += f"Prefixes removed: {', '.join(report.prefixes_removed)}\n"

                commit_info = self.git_service.commit_changes(
                    project_id=project.id,
                    ontology_content=normalized_content,
                    filename=filename,
                    message=commit_message,
                    author_name=user.name if user else "Axigraph System",
                    author_email=user.email if user else "system@axigraph.local",
                )
                commit_hash = commit_info.hash

        # Create the run record
        run = NormalizationRun(
            project_id=project.id,
            triggered_by=user.id if user else None,
            trigger_type=trigger_type,
            report_json=json.dumps(report.to_dict()),
            original_format=report.original_format,
            original_size_bytes=report.original_size_bytes,
            normalized_size_bytes=report.normalized_size_bytes,
            triple_count=report.triple_count,
            prefixes_removed_count=len(report.prefixes_removed),
            prefixes_added_count=len(report.prefixes_added),
            format_converted=report.format_converted,
            is_dry_run=dry_run,
            commit_hash=commit_hash,
        )

        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        logger.info(
            f"Normalization {'check' if dry_run else 'run'} completed for project {project.id}, "
            f"run_id={run.id}, changed={content_changed}"
        )

        # For dry runs, also return the content for diff preview
        if dry_run:
            return run, content.decode("utf-8"), normalized_content.decode("utf-8")

        return run, None, None

    async def get_normalization_history(
        self, project_id: UUID, limit: int = 10, include_dry_runs: bool = False
    ) -> list[NormalizationRun]:
        """Get normalization run history for a project."""
        query = select(NormalizationRun).where(NormalizationRun.project_id == project_id)

        if not include_dry_runs:
            query = query.where(NormalizationRun.is_dry_run == False)  # noqa: E712

        query = query.order_by(NormalizationRun.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_normalization_run(
        self, project_id: UUID, run_id: UUID
    ) -> NormalizationRun | None:
        """Get a specific normalization run."""
        result = await self.db.execute(
            select(NormalizationRun).where(
                NormalizationRun.project_id == project_id,
                NormalizationRun.id == run_id,
            )
        )
        return result.scalar_one_or_none()

    def _get_object_name(self, source_file_path: str) -> str:
        """Extract object name from source_file_path."""
        if "/" in source_file_path:
            parts = source_file_path.split("/", 1)
            return parts[1] if len(parts) > 1 else source_file_path
        return source_file_path


def get_normalization_service(
    db: AsyncSession, storage: StorageService
) -> NormalizationService:
    """Factory function for dependency injection."""
    return NormalizationService(db, storage)
