"""Git repository operations for ontology versioning."""

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from git import Actor, GitCommandError, Repo
from git.exc import InvalidGitRepositoryError
from rdflib import Graph
from rdflib.compare import graph_diff, to_isomorphic

from app.core.config import settings


@dataclass
class CommitInfo:
    """Information about a commit."""

    hash: str
    short_hash: str
    message: str
    author_name: str
    author_email: str
    timestamp: str
    is_merge: bool = False
    merged_branch: str | None = None


@dataclass
class FileChange:
    """Information about a single file change."""

    path: str
    change_type: str
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str | None = None


@dataclass
class DiffInfo:
    """Information about a diff between versions."""

    from_version: str
    to_version: str
    files_changed: int
    changes: list[FileChange]
    total_additions: int = 0
    total_deletions: int = 0


@dataclass
class BranchInfo:
    """Information about a git branch."""

    name: str
    is_current: bool = False
    is_default: bool = False
    commit_hash: str | None = None
    commit_message: str | None = None
    commit_date: datetime | None = None
    commits_ahead: int = 0
    commits_behind: int = 0


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    message: str
    merge_commit_hash: str | None = None
    conflicts: list[str] = field(default_factory=list)


class OntologyRepository:
    """Manages Git operations for an ontology repository."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self._repo: Repo | None = None

    @property
    def repo(self) -> Repo:
        """Get or initialize the Git repository."""
        if self._repo is None:
            if (self.repo_path / ".git").exists():
                self._repo = Repo(self.repo_path)
            else:
                self._repo = Repo.init(self.repo_path, initial_branch="main")
        return self._repo

    @property
    def is_initialized(self) -> bool:
        """Check if the repository has been initialized."""
        return (self.repo_path / ".git").exists()

    def commit(
        self,
        message: str,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> CommitInfo:
        """
        Commit current changes and return the commit info.

        Args:
            message: Commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            CommitInfo with details about the created commit
        """
        # Stage all changes
        self.repo.index.add("*")

        # Create author actor if provided
        author = None
        if author_name or author_email:
            author = Actor(
                name=author_name or "Unknown",
                email=author_email or "unknown@axigraph.local",
            )

        # Create commit
        commit = self.repo.index.commit(message, author=author, committer=author)

        return CommitInfo(
            hash=commit.hexsha,
            short_hash=commit.hexsha[:8],
            message=commit.message.strip(),
            author_name=str(commit.author.name) if commit.author else "Unknown",
            author_email=str(commit.author.email) if commit.author else "",
            timestamp=commit.committed_datetime.isoformat(),
        )

    def get_history(self, limit: int = 50) -> list[CommitInfo]:
        """Get commit history."""
        import re

        commits = []
        try:
            for commit in self.repo.iter_commits(max_count=limit):
                # Detect merge commits (commits with multiple parents)
                is_merge = len(commit.parents) > 1
                merged_branch = None

                if is_merge:
                    # Try to extract branch name from merge commit message
                    # Common formats: "Merge branch 'feature/x'" or "Merge branch 'feature/x' into main"
                    message = commit.message.strip()
                    match = re.search(r"Merge branch '([^']+)'", message)
                    if match:
                        merged_branch = match.group(1)

                commits.append(
                    CommitInfo(
                        hash=commit.hexsha,
                        short_hash=commit.hexsha[:8],
                        message=commit.message.strip(),
                        author_name=str(commit.author.name) if commit.author else "Unknown",
                        author_email=str(commit.author.email) if commit.author else "",
                        timestamp=commit.committed_datetime.isoformat(),
                        is_merge=is_merge,
                        merged_branch=merged_branch,
                    )
                )
        except ValueError:
            # No commits yet
            pass
        return commits

    def get_file_at_version(self, filepath: str, version: str) -> str:
        """Get file content at a specific version."""
        commit = self.repo.commit(version)
        blob = commit.tree / filepath
        return blob.data_stream.read().decode("utf-8")

    def diff_versions(self, from_version: str, to_version: str = "HEAD") -> DiffInfo:
        """Get diff between two versions with patch content and line counts."""
        from_commit = self.repo.commit(from_version)
        to_commit = self.repo.commit(to_version)

        # Get diff with patch content
        diff = from_commit.diff(to_commit, create_patch=True)

        changes: list[FileChange] = []
        total_additions = 0
        total_deletions = 0

        for d in diff:
            # Get the patch content
            patch = None
            additions = 0
            deletions = 0

            if d.diff:
                try:
                    patch = d.diff.decode("utf-8", errors="replace")
                    # Count additions and deletions from the patch
                    for line in patch.split("\n"):
                        if line.startswith("+") and not line.startswith("+++"):
                            additions += 1
                        elif line.startswith("-") and not line.startswith("---"):
                            deletions += 1
                except Exception:
                    patch = None

            total_additions += additions
            total_deletions += deletions

            changes.append(
                FileChange(
                    path=d.b_path or d.a_path or "",
                    change_type=d.change_type,
                    old_path=d.a_path if d.change_type == "R" else None,
                    additions=additions,
                    deletions=deletions,
                    patch=patch,
                )
            )

        return DiffInfo(
            from_version=from_version,
            to_version=to_version,
            files_changed=len(diff),
            changes=changes,
            total_additions=total_additions,
            total_deletions=total_deletions,
        )

    def list_files(self, version: str = "HEAD") -> list[str]:
        """List all files at a specific version."""
        try:
            commit = self.repo.commit(version)
            return [item.path for item in commit.tree.traverse() if item.type == "blob"]
        except (ValueError, InvalidGitRepositoryError):
            return []

    # Branch operations

    def get_current_branch(self) -> str:
        """Get the name of the current branch."""
        try:
            return self.repo.active_branch.name
        except TypeError:
            # Detached HEAD state
            return self.repo.head.commit.hexsha[:8]

    def get_default_branch(self) -> str:
        """Get the name of the default branch (main or master)."""
        for name in ["main", "master"]:
            if name in [b.name for b in self.repo.branches]:
                return name
        # Return first branch if neither main nor master exists
        if self.repo.branches:
            return self.repo.branches[0].name
        return "main"

    def list_branches(self) -> list[BranchInfo]:
        """List all branches with their metadata."""
        branches = []
        current_branch = self.get_current_branch()
        default_branch = self.get_default_branch()

        for branch in self.repo.branches:
            commit = branch.commit
            commits_ahead = 0
            commits_behind = 0

            # Calculate ahead/behind relative to default branch
            if branch.name != default_branch:
                try:
                    default_commit = self.repo.branches[default_branch].commit
                    # Commits ahead: commits in branch not in default
                    ahead_commits = list(
                        self.repo.iter_commits(f"{default_branch}..{branch.name}")
                    )
                    commits_ahead = len(ahead_commits)
                    # Commits behind: commits in default not in branch
                    behind_commits = list(
                        self.repo.iter_commits(f"{branch.name}..{default_branch}")
                    )
                    commits_behind = len(behind_commits)
                except (GitCommandError, KeyError):
                    pass

            branches.append(
                BranchInfo(
                    name=branch.name,
                    is_current=branch.name == current_branch,
                    is_default=branch.name == default_branch,
                    commit_hash=commit.hexsha,
                    commit_message=commit.message.strip().split("\n")[0],
                    commit_date=commit.committed_datetime,
                    commits_ahead=commits_ahead,
                    commits_behind=commits_behind,
                )
            )

        return branches

    def create_branch(self, name: str, from_ref: str = "HEAD") -> BranchInfo:
        """
        Create a new branch.

        Args:
            name: Name of the new branch
            from_ref: Reference to create branch from (commit hash, branch name, or HEAD)

        Returns:
            BranchInfo for the created branch
        """
        commit = self.repo.commit(from_ref)
        new_branch = self.repo.create_head(name, commit)

        return BranchInfo(
            name=new_branch.name,
            is_current=False,
            is_default=False,
            commit_hash=commit.hexsha,
            commit_message=commit.message.strip().split("\n")[0],
            commit_date=commit.committed_datetime,
        )

    def switch_branch(self, name: str) -> BranchInfo:
        """
        Switch to a different branch.

        Args:
            name: Name of the branch to switch to

        Returns:
            BranchInfo for the branch after switching
        """
        branch = self.repo.branches[name]
        branch.checkout()

        commit = branch.commit
        default_branch = self.get_default_branch()

        commits_ahead = 0
        commits_behind = 0
        if name != default_branch:
            try:
                ahead_commits = list(
                    self.repo.iter_commits(f"{default_branch}..{name}")
                )
                commits_ahead = len(ahead_commits)
                behind_commits = list(
                    self.repo.iter_commits(f"{name}..{default_branch}")
                )
                commits_behind = len(behind_commits)
            except GitCommandError:
                pass

        return BranchInfo(
            name=name,
            is_current=True,
            is_default=name == default_branch,
            commit_hash=commit.hexsha,
            commit_message=commit.message.strip().split("\n")[0],
            commit_date=commit.committed_datetime,
            commits_ahead=commits_ahead,
            commits_behind=commits_behind,
        )

    def delete_branch(self, name: str, force: bool = False) -> bool:
        """
        Delete a branch.

        Args:
            name: Name of the branch to delete
            force: Force delete even if branch has unmerged changes

        Returns:
            True if deletion was successful
        """
        if name == self.get_current_branch():
            raise ValueError("Cannot delete the current branch")

        if name == self.get_default_branch():
            raise ValueError("Cannot delete the default branch")

        if force:
            self.repo.delete_head(name, force=True)
        else:
            self.repo.delete_head(name)

        return True

    def merge_branch(
        self,
        source: str,
        target: str,
        message: str | None = None,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> MergeResult:
        """
        Merge source branch into target branch.

        Args:
            source: Source branch name to merge from
            target: Target branch name to merge into
            message: Custom merge commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            MergeResult with merge details
        """
        # Store current branch to restore later
        original_branch = self.get_current_branch()

        try:
            # Switch to target branch
            target_branch = self.repo.branches[target]
            target_branch.checkout()

            # Get source branch
            source_branch = self.repo.branches[source]

            # Create author actor if provided
            author = None
            if author_name or author_email:
                author = Actor(
                    name=author_name or "Unknown",
                    email=author_email or "unknown@axigraph.local",
                )

            # Perform merge
            merge_base = self.repo.merge_base(target_branch, source_branch)
            if merge_base and merge_base[0] == source_branch.commit:
                # Already merged - nothing to do
                return MergeResult(
                    success=True,
                    message="Already up to date",
                    merge_commit_hash=target_branch.commit.hexsha,
                )

            # Check if fast-forward is possible
            if merge_base and merge_base[0] == target_branch.commit:
                # Fast-forward merge
                target_branch.set_commit(source_branch.commit)
                return MergeResult(
                    success=True,
                    message="Fast-forward merge",
                    merge_commit_hash=source_branch.commit.hexsha,
                )

            # Regular merge
            merge_msg = message or f"Merge branch '{source}' into {target}"

            try:
                self.repo.git.merge(source, m=merge_msg, no_ff=True)

                # Get merge commit
                merge_commit = self.repo.head.commit

                # Update author if provided
                if author:
                    self.repo.git.commit(amend=True, author=f"{author.name} <{author.email}>", no_edit=True)
                    merge_commit = self.repo.head.commit

                return MergeResult(
                    success=True,
                    message="Merge successful",
                    merge_commit_hash=merge_commit.hexsha,
                )

            except GitCommandError as e:
                # Merge conflict
                conflicts = self.repo.index.unmerged_blobs().keys()
                # Abort the merge
                self.repo.git.merge(abort=True)

                return MergeResult(
                    success=False,
                    message="Merge failed due to conflicts",
                    conflicts=list(conflicts),
                )

        finally:
            # Restore original branch if different
            if self.get_current_branch() != original_branch:
                try:
                    self.repo.branches[original_branch].checkout()
                except (GitCommandError, KeyError):
                    pass

    def get_commits_between(
        self, from_ref: str, to_ref: str = "HEAD"
    ) -> list[CommitInfo]:
        """
        Get commits between two references.

        Args:
            from_ref: Starting reference (exclusive)
            to_ref: Ending reference (inclusive)

        Returns:
            List of CommitInfo objects
        """
        commits = []
        try:
            for commit in self.repo.iter_commits(f"{from_ref}..{to_ref}"):
                commits.append(
                    CommitInfo(
                        hash=commit.hexsha,
                        short_hash=commit.hexsha[:8],
                        message=commit.message.strip(),
                        author_name=str(commit.author.name) if commit.author else "Unknown",
                        author_email=str(commit.author.email) if commit.author else "",
                        timestamp=commit.committed_datetime.isoformat(),
                    )
                )
        except GitCommandError:
            pass
        return commits

    # Remote operations

    def add_remote(self, name: str, url: str) -> bool:
        """
        Add a remote to the repository.

        Args:
            name: Name of the remote (e.g., "origin")
            url: URL of the remote repository

        Returns:
            True if remote was added successfully
        """
        try:
            if name in [r.name for r in self.repo.remotes]:
                # Update existing remote
                self.repo.delete_remote(name)
            self.repo.create_remote(name, url)
            return True
        except GitCommandError:
            return False

    def remove_remote(self, name: str) -> bool:
        """
        Remove a remote from the repository.

        Args:
            name: Name of the remote to remove

        Returns:
            True if remote was removed successfully
        """
        try:
            self.repo.delete_remote(name)
            return True
        except GitCommandError:
            return False

    def list_remotes(self) -> list[dict[str, str]]:
        """List all remotes."""
        return [
            {"name": remote.name, "url": list(remote.urls)[0] if remote.urls else ""}
            for remote in self.repo.remotes
        ]

    def push(
        self, remote: str = "origin", branch: str | None = None, force: bool = False
    ) -> bool:
        """
        Push to a remote repository.

        Args:
            remote: Name of the remote
            branch: Branch to push (defaults to current branch)
            force: Force push

        Returns:
            True if push was successful
        """
        try:
            branch = branch or self.get_current_branch()
            remote_obj = self.repo.remote(remote)

            if force:
                remote_obj.push(branch, force=True)
            else:
                remote_obj.push(branch)
            return True
        except GitCommandError:
            return False

    def pull(self, remote: str = "origin", branch: str | None = None) -> bool:
        """
        Pull from a remote repository.

        Args:
            remote: Name of the remote
            branch: Branch to pull (defaults to current branch)

        Returns:
            True if pull was successful
        """
        try:
            branch = branch or self.get_current_branch()
            remote_obj = self.repo.remote(remote)
            remote_obj.pull(branch)
            return True
        except GitCommandError:
            return False

    def fetch(self, remote: str = "origin") -> bool:
        """
        Fetch from a remote repository.

        Args:
            remote: Name of the remote

        Returns:
            True if fetch was successful
        """
        try:
            remote_obj = self.repo.remote(remote)
            remote_obj.fetch()
            return True
        except GitCommandError:
            return False


class GitRepositoryService:
    """
    Service for managing git repositories for projects.

    Each project gets its own git repository for tracking ontology changes.
    """

    def __init__(self, base_path: str | None = None) -> None:
        """
        Initialize the service.

        Args:
            base_path: Base path for storing repositories. Defaults to settings.
        """
        self.base_path = Path(base_path or settings.git_repos_base_path)

    def _get_project_repo_path(self, project_id: UUID) -> Path:
        """Get the repository path for a project."""
        return self.base_path / str(project_id)

    def get_repository(self, project_id: UUID) -> OntologyRepository:
        """
        Get the OntologyRepository for a project.

        Args:
            project_id: The project's UUID

        Returns:
            OntologyRepository instance for the project
        """
        repo_path = self._get_project_repo_path(project_id)
        return OntologyRepository(repo_path)

    def initialize_repository(
        self,
        project_id: UUID,
        ontology_content: bytes,
        filename: str,
        author_name: str | None = None,
        author_email: str | None = None,
        project_name: str | None = None,
    ) -> CommitInfo:
        """
        Initialize a git repository for a project with the initial ontology file.

        Args:
            project_id: The project's UUID
            ontology_content: The ontology file content
            filename: The filename to use (e.g., "ontology.ttl")
            author_name: Author's display name
            author_email: Author's email address
            project_name: Project name for the commit message

        Returns:
            CommitInfo for the initial commit
        """
        repo_path = self._get_project_repo_path(project_id)

        # Create directory if it doesn't exist
        repo_path.mkdir(parents=True, exist_ok=True)

        # Write the ontology file
        ontology_file = repo_path / filename
        ontology_file.write_bytes(ontology_content)

        # Initialize repo and create initial commit
        repo = OntologyRepository(repo_path)
        message = f"Initial import of {project_name or 'ontology'}"

        return repo.commit(
            message=message,
            author_name=author_name,
            author_email=author_email,
        )

    def commit_changes(
        self,
        project_id: UUID,
        ontology_content: bytes,
        filename: str,
        message: str,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> CommitInfo:
        """
        Commit changes to the ontology file.

        Args:
            project_id: The project's UUID
            ontology_content: The updated ontology file content
            filename: The filename to update
            message: Commit message describing the changes
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            CommitInfo for the new commit
        """
        repo_path = self._get_project_repo_path(project_id)

        # Write the updated ontology file
        ontology_file = repo_path / filename
        ontology_file.write_bytes(ontology_content)

        # Commit changes
        repo = OntologyRepository(repo_path)
        return repo.commit(
            message=message,
            author_name=author_name,
            author_email=author_email,
        )

    def get_history(self, project_id: UUID, limit: int = 50) -> list[CommitInfo]:
        """
        Get commit history for a project.

        Args:
            project_id: The project's UUID
            limit: Maximum number of commits to return

        Returns:
            List of CommitInfo objects
        """
        repo = self.get_repository(project_id)
        return repo.get_history(limit=limit)

    def get_file_at_version(
        self, project_id: UUID, filename: str, version: str
    ) -> str:
        """
        Get ontology file content at a specific version.

        Args:
            project_id: The project's UUID
            filename: The filename to retrieve
            version: Git commit hash or reference

        Returns:
            File content as string
        """
        repo = self.get_repository(project_id)
        return repo.get_file_at_version(filename, version)

    def diff_versions(
        self, project_id: UUID, from_version: str, to_version: str = "HEAD"
    ) -> DiffInfo:
        """
        Get diff between two versions.

        Args:
            project_id: The project's UUID
            from_version: Starting version (commit hash)
            to_version: Ending version (commit hash or "HEAD")

        Returns:
            DiffInfo with change details
        """
        repo = self.get_repository(project_id)
        return repo.diff_versions(from_version, to_version)

    def delete_repository(self, project_id: UUID) -> None:
        """
        Delete the git repository for a project.

        Args:
            project_id: The project's UUID
        """
        repo_path = self._get_project_repo_path(project_id)
        if repo_path.exists():
            shutil.rmtree(repo_path)

    def repository_exists(self, project_id: UUID) -> bool:
        """
        Check if a repository exists for a project.

        Args:
            project_id: The project's UUID

        Returns:
            True if repository exists
        """
        repo = self.get_repository(project_id)
        return repo.is_initialized

    # Branch operations

    def get_current_branch(self, project_id: UUID) -> str:
        """Get the current branch for a project."""
        repo = self.get_repository(project_id)
        return repo.get_current_branch()

    def get_default_branch(self, project_id: UUID) -> str:
        """Get the default branch for a project."""
        repo = self.get_repository(project_id)
        return repo.get_default_branch()

    def list_branches(self, project_id: UUID) -> list[BranchInfo]:
        """List all branches for a project."""
        repo = self.get_repository(project_id)
        return repo.list_branches()

    def create_branch(
        self, project_id: UUID, name: str, from_ref: str = "HEAD"
    ) -> BranchInfo:
        """
        Create a new branch for a project.

        Args:
            project_id: The project's UUID
            name: Name of the new branch
            from_ref: Reference to create branch from

        Returns:
            BranchInfo for the created branch
        """
        repo = self.get_repository(project_id)
        return repo.create_branch(name, from_ref)

    def switch_branch(self, project_id: UUID, name: str) -> BranchInfo:
        """
        Switch to a different branch for a project.

        Args:
            project_id: The project's UUID
            name: Name of the branch to switch to

        Returns:
            BranchInfo for the branch after switching
        """
        repo = self.get_repository(project_id)
        return repo.switch_branch(name)

    def delete_branch(
        self, project_id: UUID, name: str, force: bool = False
    ) -> bool:
        """
        Delete a branch for a project.

        Args:
            project_id: The project's UUID
            name: Name of the branch to delete
            force: Force delete even if branch has unmerged changes

        Returns:
            True if deletion was successful
        """
        repo = self.get_repository(project_id)
        return repo.delete_branch(name, force)

    def merge_branch(
        self,
        project_id: UUID,
        source: str,
        target: str,
        message: str | None = None,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> MergeResult:
        """
        Merge source branch into target branch.

        Args:
            project_id: The project's UUID
            source: Source branch name
            target: Target branch name
            message: Custom merge commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            MergeResult with merge details
        """
        repo = self.get_repository(project_id)
        return repo.merge_branch(source, target, message, author_name, author_email)

    def get_commits_between(
        self, project_id: UUID, from_ref: str, to_ref: str = "HEAD"
    ) -> list[CommitInfo]:
        """
        Get commits between two references.

        Args:
            project_id: The project's UUID
            from_ref: Starting reference
            to_ref: Ending reference

        Returns:
            List of CommitInfo objects
        """
        repo = self.get_repository(project_id)
        return repo.get_commits_between(from_ref, to_ref)

    def commit_to_branch(
        self,
        project_id: UUID,
        branch_name: str,
        ontology_content: bytes,
        filename: str,
        message: str,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> CommitInfo:
        """
        Switch to branch and commit changes.

        Args:
            project_id: The project's UUID
            branch_name: Branch to commit to
            ontology_content: The ontology file content
            filename: The filename to update
            message: Commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            CommitInfo for the new commit
        """
        repo = self.get_repository(project_id)

        # Store current branch
        original_branch = repo.get_current_branch()

        try:
            # Switch to target branch if needed
            if original_branch != branch_name:
                repo.switch_branch(branch_name)

            # Write the updated ontology file
            ontology_file = repo.repo_path / filename
            ontology_file.write_bytes(ontology_content)

            # Commit changes
            return repo.commit(
                message=message,
                author_name=author_name,
                author_email=author_email,
            )
        finally:
            # Restore original branch if different
            if original_branch != branch_name:
                try:
                    repo.switch_branch(original_branch)
                except (GitCommandError, KeyError):
                    pass

    # Remote operations

    def setup_remote(
        self, project_id: UUID, remote_url: str, remote_name: str = "origin"
    ) -> bool:
        """
        Setup a remote for a project.

        Args:
            project_id: The project's UUID
            remote_url: URL of the remote repository
            remote_name: Name of the remote

        Returns:
            True if remote was setup successfully
        """
        repo = self.get_repository(project_id)
        return repo.add_remote(remote_name, remote_url)

    def push_branch(
        self,
        project_id: UUID,
        branch_name: str | None = None,
        remote: str = "origin",
        force: bool = False,
    ) -> bool:
        """
        Push a branch to remote.

        Args:
            project_id: The project's UUID
            branch_name: Branch to push (defaults to current)
            remote: Name of the remote
            force: Force push

        Returns:
            True if push was successful
        """
        repo = self.get_repository(project_id)
        return repo.push(remote, branch_name, force)

    def pull_branch(
        self,
        project_id: UUID,
        branch_name: str | None = None,
        remote: str = "origin",
    ) -> bool:
        """
        Pull a branch from remote.

        Args:
            project_id: The project's UUID
            branch_name: Branch to pull (defaults to current)
            remote: Name of the remote

        Returns:
            True if pull was successful
        """
        repo = self.get_repository(project_id)
        return repo.pull(remote, branch_name)

    def fetch_remote(self, project_id: UUID, remote: str = "origin") -> bool:
        """
        Fetch from remote.

        Args:
            project_id: The project's UUID
            remote: Name of the remote

        Returns:
            True if fetch was successful
        """
        repo = self.get_repository(project_id)
        return repo.fetch(remote)

    def list_remotes(self, project_id: UUID) -> list[dict[str, str]]:
        """List all remotes for a project."""
        repo = self.get_repository(project_id)
        return repo.list_remotes()


def get_git_service() -> GitRepositoryService:
    """Factory function for dependency injection."""
    return GitRepositoryService()


def serialize_deterministic(graph: Graph) -> str:
    """
    Serialize graph to Turtle with deterministic triple ordering.

    This ensures consistent diffs in version control.
    """
    iso_graph = to_isomorphic(graph)
    return iso_graph.serialize(format="turtle")


def semantic_diff(old_graph: Graph, new_graph: Graph) -> dict[str, Any]:
    """
    Compute semantic diff between two graphs.

    Returns added/removed triples regardless of serialization order.
    """
    in_both, in_old, in_new = graph_diff(old_graph, new_graph)

    return {
        "added": [
            {"subject": str(s), "predicate": str(p), "object": str(o)}
            for s, p, o in in_new
        ],
        "removed": [
            {"subject": str(s), "predicate": str(p), "object": str(o)}
            for s, p, o in in_old
        ],
        "added_count": len(in_new),
        "removed_count": len(in_old),
        "unchanged_count": len(in_both),
    }
