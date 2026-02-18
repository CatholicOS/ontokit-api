#!/usr/bin/env python3
"""
Migration script to convert working-directory Git repositories to bare repositories.

This script is used to migrate existing projects from the old GitPython-based
working-directory repositories to the new pygit2-based bare repositories.

Usage:
    python scripts/migrate_to_bare_repos.py [--dry-run] [--keep-old]

Arguments:
    --dry-run    Show what would be migrated without making changes
    --keep-old   Keep the old repositories after migration (default: remove them)
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path
from uuid import UUID

import pygit2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def is_working_directory_repo(path: Path) -> bool:
    """Check if path is a working-directory repository (has .git folder)."""
    return (path / ".git").is_dir()


def is_bare_repo(path: Path) -> bool:
    """Check if path is already a bare repository."""
    # Bare repos have HEAD file directly in the repo directory
    return (path / "HEAD").is_file() and not (path / ".git").exists()


def migrate_repo_to_bare(
    source_path: Path,
    target_path: Path,
    dry_run: bool = False,
) -> bool:
    """
    Migrate a working-directory repository to a bare repository.

    Args:
        source_path: Path to the working-directory repo
        target_path: Path for the new bare repo (should end with .git)
        dry_run: If True, only log what would be done

    Returns:
        True if migration was successful
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would migrate: {source_path} -> {target_path}")
        return True

    try:
        # Clone the working-directory repo to a bare repo
        logger.info(f"Cloning {source_path} to bare repo {target_path}")

        # Use pygit2 to clone as bare
        pygit2.clone_repository(
            str(source_path),
            str(target_path),
            bare=True,
        )

        # Verify the clone
        bare_repo = pygit2.Repository(str(target_path))

        # Count branches
        branch_count = sum(
            1 for ref in bare_repo.references
            if ref.startswith("refs/heads/")
        )

        # Count commits (on default branch)
        commit_count = 0
        try:
            for ref_name in bare_repo.references:
                if ref_name.startswith("refs/heads/"):
                    ref = bare_repo.references[ref_name]
                    for _ in bare_repo.walk(ref.target, pygit2.GIT_SORT_TIME):
                        commit_count += 1
                    break
        except Exception:
            pass

        logger.info(
            f"Successfully created bare repo with {branch_count} branches, "
            f"~{commit_count} commits"
        )

        return True

    except Exception as e:
        logger.error(f"Failed to migrate {source_path}: {e}")
        # Clean up partial migration
        if target_path.exists():
            shutil.rmtree(target_path)
        return False


def migrate_all_repos(
    base_path: Path,
    dry_run: bool = False,
    keep_old: bool = False,
) -> tuple[int, int, int]:
    """
    Migrate all repositories in the base path.

    Args:
        base_path: Base path where repositories are stored
        dry_run: If True, only log what would be done
        keep_old: If True, keep old repos after migration

    Returns:
        Tuple of (migrated_count, skipped_count, failed_count)
    """
    if not base_path.exists():
        logger.error(f"Base path does not exist: {base_path}")
        return 0, 0, 0

    migrated = 0
    skipped = 0
    failed = 0

    # Find all directories in base path
    for item in base_path.iterdir():
        if not item.is_dir():
            continue

        # Check if it's a UUID (project ID)
        try:
            project_id = UUID(item.name.replace(".git", ""))
        except ValueError:
            logger.debug(f"Skipping non-UUID directory: {item.name}")
            continue

        # Determine repo type and migration need
        if item.name.endswith(".git"):
            if is_bare_repo(item):
                logger.info(f"Skipping {item.name} - already a bare repo")
                skipped += 1
                continue
        elif is_working_directory_repo(item):
            # This is a working-directory repo that needs migration
            target_path = base_path / f"{project_id}.git"

            if target_path.exists():
                logger.warning(
                    f"Target {target_path} already exists, skipping {item.name}"
                )
                skipped += 1
                continue

            logger.info(f"Migrating working-directory repo: {item.name}")

            if migrate_repo_to_bare(item, target_path, dry_run):
                migrated += 1

                # Remove old repo if not keeping
                if not dry_run and not keep_old:
                    logger.info(f"Removing old working-directory repo: {item}")
                    shutil.rmtree(item)
            else:
                failed += 1
        else:
            logger.debug(f"Skipping unknown directory type: {item.name}")

    return migrated, skipped, failed


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate Git repositories from working-directory to bare format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--keep-old",
        action="store_true",
        help="Keep old repositories after migration",
    )
    parser.add_argument(
        "--base-path",
        type=Path,
        default=None,
        help="Base path for repositories (default: from settings)",
    )

    args = parser.parse_args()

    # Get base path
    if args.base_path:
        base_path = args.base_path
    else:
        # Try to load from settings
        try:
            from axigraph.core.config import settings
            base_path = Path(settings.git_repos_base_path)
        except ImportError:
            # Default fallback
            base_path = Path("/data/repos")
            logger.warning(f"Could not load settings, using default: {base_path}")

    logger.info(f"{'[DRY RUN] ' if args.dry_run else ''}Starting migration")
    logger.info(f"Base path: {base_path}")
    logger.info(f"Keep old repos: {args.keep_old}")

    migrated, skipped, failed = migrate_all_repos(
        base_path,
        dry_run=args.dry_run,
        keep_old=args.keep_old,
    )

    logger.info(f"Migration complete:")
    logger.info(f"  Migrated: {migrated}")
    logger.info(f"  Skipped:  {skipped}")
    logger.info(f"  Failed:   {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
