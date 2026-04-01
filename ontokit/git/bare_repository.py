"""Bare Git repository operations using pygit2 for concurrent access.

This module provides thread-safe git operations using bare repositories,
allowing multiple users to work on different branches simultaneously
without the limitations of working directory-based operations.
"""

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pygit2
from rdflib import Graph, URIRef
from rdflib.compare import graph_diff, to_isomorphic

from ontokit.core.config import settings


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
    parent_hashes: list[str] = field(default_factory=list)


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
    remote_commits_ahead: int | None = None
    remote_commits_behind: int | None = None


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    message: str
    merge_commit_hash: str | None = None
    conflicts: list[str] = field(default_factory=list)


class BareOntologyRepository:
    """
    Manages Git operations using a bare repository for concurrent access.

    Unlike working-directory based repos, bare repos allow multiple users
    to work on different branches simultaneously without conflicts.
    All file operations are done directly on git objects.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self._repo: pygit2.Repository | None = None

    @property
    def repo(self) -> pygit2.Repository:
        """Get or initialize the bare Git repository."""
        if self._repo is None:
            if self.repo_path.exists() and (self.repo_path / "HEAD").exists():
                self._repo = pygit2.Repository(str(self.repo_path))
            else:
                # Initialize a bare repository
                self.repo_path.mkdir(parents=True, exist_ok=True)
                self._repo = pygit2.init_repository(str(self.repo_path), bare=True)
                # Set default branch to main
                self._repo.set_head("refs/heads/main")
        return self._repo

    @property
    def is_initialized(self) -> bool:
        """Check if the repository has been initialized."""
        return self.repo_path.exists() and (self.repo_path / "HEAD").exists()

    def _get_signature(self, name: str | None = None, email: str | None = None) -> pygit2.Signature:
        """Create a pygit2 signature for commits."""
        return pygit2.Signature(
            name=name or "OntoKit",
            email=email or "noreply@ontokit.dev",
        )

    def _resolve_ref(self, ref: str) -> pygit2.Commit:
        """Resolve a reference (branch name, commit hash, HEAD) to a commit."""
        if ref == "HEAD":
            try:
                return self.repo.head.peel(pygit2.Commit)
            except (KeyError, ValueError):
                # HEAD points to a non-existent branch; reset to default
                default = self.get_default_branch()
                branch_ref = f"refs/heads/{default}"
                if branch_ref in self.repo.references:
                    self.repo.set_head(branch_ref)
                    return self.repo.references[branch_ref].peel(pygit2.Commit)
                raise ValueError(
                    f"HEAD is broken and default branch '{default}' not found"
                ) from None

        # Try as branch name
        branch_ref = f"refs/heads/{ref}"
        if branch_ref in self.repo.references:
            return self.repo.references[branch_ref].peel(pygit2.Commit)

        # Try as commit hash
        try:
            obj = self.repo.get(ref)
            if isinstance(obj, pygit2.Commit):
                return obj
            if isinstance(obj, pygit2.Tag):
                return obj.peel(pygit2.Commit)
        except (KeyError, ValueError):
            pass

        # Try as partial hash
        try:
            for commit in self.repo.walk(self.repo.head.target, pygit2.GIT_SORT_TIME):  # type: ignore[arg-type]
                if str(commit.id).startswith(ref):
                    return commit
        except Exception:
            pass

        raise ValueError(f"Cannot resolve reference: {ref}")

    def _commit_to_info(self, commit: pygit2.Commit) -> CommitInfo:
        """Convert a pygit2 Commit to CommitInfo."""
        import re

        is_merge = len(commit.parents) > 1
        merged_branch = None

        if is_merge:
            message = commit.message.strip()
            match = re.search(r"Merge branch '([^']+)'", message)
            if match:
                merged_branch = match.group(1)

        commit_hash = str(commit.id)
        return CommitInfo(
            hash=commit_hash,
            short_hash=commit_hash[:8],
            message=commit.message.strip(),
            author_name=commit.author.name,
            author_email=commit.author.email,
            timestamp=datetime.fromtimestamp(commit.commit_time, tz=UTC).isoformat(),
            is_merge=is_merge,
            merged_branch=merged_branch,
            parent_hashes=[str(p.id) for p in commit.parents],
        )

    def write_file(
        self,
        branch_name: str,
        filepath: str,
        content: bytes,
        message: str,
        author_name: str | None = None,
        author_email: str | None = None,
    ) -> CommitInfo:
        """
        Write a file to a branch and create a commit.

        This is the core operation for bare repos - it creates a blob,
        updates the tree, and creates a commit all without a working directory.

        Args:
            branch_name: Branch to commit to
            filepath: Path within the repository
            content: File content as bytes
            message: Commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            CommitInfo with details about the created commit
        """
        branch_ref = f"refs/heads/{branch_name}"

        # Create blob from content
        blob_id = self.repo.create_blob(content)

        # Get parent commit and tree (if branch exists)
        parent_commit = None
        parent_tree = None

        if branch_ref in self.repo.references:
            parent_commit = self.repo.references[branch_ref].peel(pygit2.Commit)
            parent_tree = parent_commit.tree

        # Build new tree with the file
        tree_builder = (
            self.repo.TreeBuilder(parent_tree) if parent_tree else self.repo.TreeBuilder()
        )

        # Handle nested paths by building intermediate trees
        parts = filepath.split("/")
        if len(parts) > 1:
            # Need to handle nested directories
            tree_builder = self._add_nested_blob(tree_builder, parent_tree, parts, blob_id)
        else:
            tree_builder.insert(filepath, blob_id, pygit2.GIT_FILEMODE_BLOB)

        new_tree_id = tree_builder.write()

        # Create commit
        author = self._get_signature(author_name, author_email)
        committer = author

        parents = [parent_commit.id] if parent_commit else []

        commit_id = self.repo.create_commit(
            branch_ref,  # Update this reference
            author,
            committer,
            message,
            new_tree_id,
            parents,
        )

        commit = cast(pygit2.Commit, self.repo.get(commit_id))
        return self._commit_to_info(commit)

    def _add_nested_blob(
        self,
        root_builder: pygit2.TreeBuilder,
        parent_tree: pygit2.Tree | None,
        parts: list[str],
        blob_id: pygit2.Oid,
    ) -> pygit2.TreeBuilder:
        """Add a blob at a nested path, creating intermediate trees as needed."""
        if len(parts) == 1:
            # Base case: add blob to current tree
            root_builder.insert(parts[0], blob_id, pygit2.GIT_FILEMODE_BLOB)
            return root_builder

        # Recursive case: need to update/create subtree
        dir_name = parts[0]
        remaining_parts = parts[1:]

        # Get existing subtree if it exists
        existing_subtree = None
        if parent_tree:
            try:
                entry = parent_tree[dir_name]
                if entry.type == pygit2.GIT_OBJECT_TREE:
                    existing_subtree = self.repo.get(entry.id)
            except KeyError:
                pass

        # Build subtree
        subtree_builder = (
            self.repo.TreeBuilder(cast(pygit2.Tree, existing_subtree))
            if existing_subtree
            else self.repo.TreeBuilder()
        )

        # Recursively add to subtree
        subtree_builder = self._add_nested_blob(
            subtree_builder,
            cast(pygit2.Tree, existing_subtree) if existing_subtree else None,
            remaining_parts,
            blob_id,
        )

        # Write subtree and add to parent
        subtree_id = subtree_builder.write()
        root_builder.insert(dir_name, subtree_id, pygit2.GIT_FILEMODE_TREE)

        return root_builder

    def read_file(self, branch_or_commit: str, filepath: str) -> bytes:
        """
        Read a file from a specific branch or commit.

        Args:
            branch_or_commit: Branch name or commit hash
            filepath: Path within the repository

        Returns:
            File content as bytes
        """
        commit = self._resolve_ref(branch_or_commit)
        tree = commit.tree

        # Navigate to the file
        parts = filepath.split("/")
        current = tree

        for i, part in enumerate(parts):
            entry = current[part]
            if i == len(parts) - 1:
                # Last part - should be a blob
                blob = cast(pygit2.Blob, self.repo.get(entry.id))
                return blob.data
            else:
                # Intermediate part - should be a tree
                current = cast(pygit2.Tree, self.repo.get(entry.id))

        raise FileNotFoundError(f"File not found: {filepath}")

    def get_history(
        self, branch: str | None = None, limit: int = 50, all_branches: bool = True
    ) -> list[CommitInfo]:
        """
        Get commit history.

        Args:
            branch: Specific branch to get history for (None for default)
            limit: Maximum number of commits to return
            all_branches: If True, include commits from all branches
        """
        commits = []
        seen_hashes = set()

        try:
            if all_branches:
                # Get commits from all branches
                all_commits = []
                for ref_name in self.repo.references:
                    if ref_name.startswith("refs/heads/"):
                        ref = self.repo.references[ref_name]
                        for commit in self.repo.walk(ref.target, pygit2.GIT_SORT_TIME):  # type: ignore[arg-type]
                            commit_hash = str(commit.id)
                            if commit_hash not in seen_hashes:
                                seen_hashes.add(commit_hash)
                                all_commits.append(commit)

                # Sort by commit time (newest first)
                all_commits.sort(key=lambda c: c.commit_time, reverse=True)
                commit_iter = all_commits[:limit]
            else:
                # Get history for specific branch or HEAD
                if branch:
                    ref = self.repo.references[f"refs/heads/{branch}"]
                    target = ref.target
                else:
                    target = self.repo.head.target

                commit_iter = []
                for count, commit in enumerate(self.repo.walk(target, pygit2.GIT_SORT_TIME)):  # type: ignore[arg-type]
                    commit_iter.append(commit)
                    if count + 1 >= limit:
                        break

            for commit in commit_iter:
                commits.append(self._commit_to_info(commit))

        except Exception:
            # No commits yet or other error
            pass

        return commits

    def get_file_at_version(self, filepath: str, version: str) -> str:
        """Get file content at a specific version as string."""
        return self.read_file(version, filepath).decode("utf-8")

    def diff_versions(self, from_version: str, to_version: str = "HEAD") -> DiffInfo:
        """Get diff between two versions."""
        from_commit = self._resolve_ref(from_version)
        to_commit = self._resolve_ref(to_version)

        diff = self.repo.diff(from_commit.tree, to_commit.tree)  # type: ignore[call-overload]

        changes: list[FileChange] = []
        total_additions = 0
        total_deletions = 0

        for patch in diff:
            delta = patch.delta

            # Map status to change type
            status_map = {
                pygit2.GIT_DELTA_ADDED: "A",
                pygit2.GIT_DELTA_DELETED: "D",
                pygit2.GIT_DELTA_MODIFIED: "M",
                pygit2.GIT_DELTA_RENAMED: "R",
                pygit2.GIT_DELTA_COPIED: "C",
            }
            change_type = status_map.get(delta.status, "M")

            # Get patch text and count lines
            patch_text = patch.text if hasattr(patch, "text") else None
            additions = 0
            deletions = 0

            if patch_text:
                for line in patch_text.split("\n"):
                    if line.startswith("+") and not line.startswith("+++"):
                        additions += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        deletions += 1

            total_additions += additions
            total_deletions += deletions

            changes.append(
                FileChange(
                    path=delta.new_file.path or delta.old_file.path or "",
                    change_type=change_type,
                    old_path=delta.old_file.path if change_type == "R" else None,
                    additions=additions,
                    deletions=deletions,
                    patch=patch_text,
                )
            )

        return DiffInfo(
            from_version=from_version,
            to_version=to_version,
            files_changed=len(changes),
            changes=changes,
            total_additions=total_additions,
            total_deletions=total_deletions,
        )

    def list_files(self, version: str = "HEAD") -> list[str]:
        """List all files at a specific version."""
        try:
            commit = self._resolve_ref(version)
            files = []

            def walk_tree(tree: pygit2.Tree, prefix: str = "") -> None:
                for entry in tree:
                    name = entry.name or ""
                    path = f"{prefix}{name}" if prefix else name
                    if entry.type == pygit2.GIT_OBJECT_BLOB:
                        files.append(path)
                    elif entry.type == pygit2.GIT_OBJECT_TREE:
                        subtree = cast(pygit2.Tree, self.repo.get(entry.id))
                        walk_tree(subtree, f"{path}/")

            walk_tree(commit.tree)
            return files
        except Exception:
            return []

    # Branch operations

    def get_current_branch(self) -> str:
        """Get the current branch by reading HEAD."""
        if self.repo.head_is_unborn:
            return self.get_default_branch()
        try:
            ref = self.repo.references["HEAD"]
            # HEAD is a symbolic ref pointing to refs/heads/<branch>
            target = ref.target
            if isinstance(target, str) and target.startswith("refs/heads/"):
                return target.replace("refs/heads/", "")
        except (KeyError, Exception):
            pass
        return self.get_default_branch()

    def get_default_branch(self) -> str:
        """Get the name of the default branch."""
        for name in ["main", "master"]:
            if f"refs/heads/{name}" in self.repo.references:
                return name

        # Return first branch if neither main nor master exists
        for ref_name in self.repo.references:
            if ref_name.startswith("refs/heads/"):
                return ref_name.replace("refs/heads/", "")

        return "main"

    def get_branch_commit_hash(self, ref: str) -> str:
        """Get the commit hash for a branch name or ref.

        Args:
            ref: Branch name, commit hash, or "HEAD"

        Returns:
            The full commit hash as a string
        """
        commit = self._resolve_ref(ref)
        return str(commit.id)

    def list_branches(self) -> list[BranchInfo]:
        """List all branches with their metadata."""
        branches = []
        current_branch = self.get_current_branch()
        default_branch = self.get_default_branch()

        for ref_name in self.repo.references:
            if not ref_name.startswith("refs/heads/"):
                continue

            branch_name = ref_name.replace("refs/heads/", "")
            ref = self.repo.references[ref_name]
            commit = ref.peel(pygit2.Commit)

            commits_ahead = 0
            commits_behind = 0

            # Calculate ahead/behind relative to default branch
            if branch_name != default_branch:
                try:
                    default_ref = self.repo.references[f"refs/heads/{default_branch}"]
                    ahead, behind = self.repo.ahead_behind(ref.target, default_ref.target)
                    commits_ahead = ahead
                    commits_behind = behind
                except Exception:
                    pass

            # Calculate ahead/behind relative to remote tracking ref
            remote_commits_ahead: int | None = None
            remote_commits_behind: int | None = None
            remote_ref_name = f"refs/remotes/origin/{branch_name}"
            if remote_ref_name in self.repo.references:
                try:
                    remote_ref = self.repo.references[remote_ref_name]
                    r_ahead, r_behind = self.repo.ahead_behind(ref.target, remote_ref.target)
                    remote_commits_ahead = r_ahead
                    remote_commits_behind = r_behind
                except Exception:
                    pass

            branches.append(
                BranchInfo(
                    name=branch_name,
                    is_current=branch_name == current_branch,
                    is_default=branch_name == default_branch,
                    commit_hash=str(commit.id),
                    commit_message=commit.message.strip().split("\n")[0],
                    commit_date=datetime.fromtimestamp(commit.commit_time, tz=UTC),
                    commits_ahead=commits_ahead,
                    commits_behind=commits_behind,
                    remote_commits_ahead=remote_commits_ahead,
                    remote_commits_behind=remote_commits_behind,
                )
            )

        return branches

    def create_branch(self, name: str, from_ref: str = "HEAD") -> BranchInfo:
        """
        Create a new branch.

        Args:
            name: Name of the new branch
            from_ref: Reference to create branch from

        Returns:
            BranchInfo for the created branch
        """
        commit = self._resolve_ref(from_ref)

        # Create branch reference
        ref_name = f"refs/heads/{name}"
        self.repo.references.create(ref_name, commit.id)

        return BranchInfo(
            name=name,
            is_current=False,
            is_default=False,
            commit_hash=str(commit.id),
            commit_message=commit.message.strip().split("\n")[0],
            commit_date=datetime.fromtimestamp(commit.commit_time, tz=UTC),
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
        if name == self.get_default_branch():
            raise ValueError("Cannot delete the default branch")

        ref_name = f"refs/heads/{name}"
        if ref_name not in self.repo.references:
            raise ValueError(f"Branch not found: {name}")

        # Check if branch is merged (unless force)
        if not force:
            default_ref = self.repo.references[f"refs/heads/{self.get_default_branch()}"]
            branch_ref = self.repo.references[ref_name]

            # Check if all commits in branch are in default
            ahead, _ = self.repo.ahead_behind(branch_ref.target, default_ref.target)
            if ahead > 0:
                raise ValueError(
                    f"Branch '{name}' has {ahead} unmerged commits. Use force=True to delete."
                )

        # If HEAD points to the branch being deleted, reset to default
        try:
            if self.repo.head.name == ref_name:
                default_ref_str = f"refs/heads/{self.get_default_branch()}"
                self.repo.set_head(default_ref_str)
        except Exception:
            pass

        self.repo.references.delete(ref_name)
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

        This creates a merge commit directly without needing checkout.

        Args:
            source: Source branch name to merge from
            target: Target branch name to merge into
            message: Custom merge commit message
            author_name: Author's display name
            author_email: Author's email address

        Returns:
            MergeResult with merge details
        """
        source_ref = f"refs/heads/{source}"
        target_ref = f"refs/heads/{target}"

        if source_ref not in self.repo.references:
            raise ValueError(f"Source branch not found: {source}")
        if target_ref not in self.repo.references:
            raise ValueError(f"Target branch not found: {target}")

        source_commit = self.repo.references[source_ref].peel(pygit2.Commit)
        target_commit = self.repo.references[target_ref].peel(pygit2.Commit)

        # Check merge base
        merge_base = self.repo.merge_base(target_commit.id, source_commit.id)

        if merge_base == source_commit.id:
            # Already merged
            return MergeResult(
                success=True,
                message="Already up to date",
                merge_commit_hash=str(target_commit.id),
            )

        # Perform merge (index-based, no working directory needed)
        merge_index = self.repo.merge_commits(target_commit, source_commit)

        if merge_index.conflicts:
            # Merge conflicts
            conflict_paths = list(
                {
                    entry[0].path if entry[0] else entry[1].path if entry[1] else entry[2].path
                    for entry in merge_index.conflicts
                    if any(entry)
                }
            )
            return MergeResult(
                success=False,
                message="Merge failed due to conflicts",
                conflicts=conflict_paths,
            )

        # Write merged tree
        merged_tree_id = merge_index.write_tree(self.repo)

        # Create merge commit
        merge_msg = message or f"Merge branch '{source}' into {target}"
        author = self._get_signature(author_name, author_email)

        commit_id = self.repo.create_commit(
            target_ref,
            author,
            author,
            merge_msg,
            merged_tree_id,
            [target_commit.id, source_commit.id],
        )

        return MergeResult(
            success=True,
            message="Merge successful",
            merge_commit_hash=str(commit_id),
        )

    def get_commits_between(self, from_ref: str, to_ref: str = "HEAD") -> list[CommitInfo]:
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
            from_commit = self._resolve_ref(from_ref)
            to_commit = self._resolve_ref(to_ref)

            # Get commits reachable from to_ref but not from from_ref
            from_ancestors = set()
            for commit in self.repo.walk(from_commit.id, pygit2.GIT_SORT_TIME):  # type: ignore[arg-type]
                from_ancestors.add(str(commit.id))

            for commit in self.repo.walk(to_commit.id, pygit2.GIT_SORT_TIME):  # type: ignore[arg-type]
                if str(commit.id) in from_ancestors:
                    break
                commits.append(self._commit_to_info(commit))

        except Exception:
            pass

        return commits

    # Remote operations

    def add_remote(self, name: str, url: str) -> bool:
        """Add or update a remote."""
        try:
            # Remove existing remote if it exists
            if name in [r.name for r in self.repo.remotes]:
                self.repo.remotes.delete(name)

            self.repo.remotes.create(name, url)
            return True
        except Exception:
            return False

    def remove_remote(self, name: str) -> bool:
        """Remove a remote."""
        try:
            self.repo.remotes.delete(name)
            return True
        except Exception:
            return False

    def list_remotes(self) -> list[dict[str, str]]:
        """List all remotes."""
        return [
            {"name": remote.name or "", "url": remote.url or ""} for remote in self.repo.remotes
        ]

    def push(
        self,
        remote: str = "origin",
        branch: str | None = None,
        force: bool = False,
        token: str | None = None,
    ) -> bool:
        """Push to a remote repository."""
        try:
            remote_obj = self.repo.remotes[remote]
            branch = branch or self.get_default_branch()
            refspec = (
                f"+refs/heads/{branch}:refs/heads/{branch}"
                if force
                else f"refs/heads/{branch}:refs/heads/{branch}"
            )
            callbacks = None
            if token:
                credentials = pygit2.UserPass("x-access-token", token)
                callbacks = pygit2.RemoteCallbacks(credentials=credentials)
            remote_obj.push([refspec], callbacks=callbacks)
            return True
        except Exception:
            return False

    def fetch(self, remote: str = "origin", token: str | None = None) -> bool:
        """Fetch from a remote repository."""
        try:
            remote_obj = self.repo.remotes[remote]
            callbacks = None
            if token:
                credentials = pygit2.UserPass("x-access-token", token)
                callbacks = pygit2.RemoteCallbacks(credentials=credentials)
            remote_obj.fetch(callbacks=callbacks)
            return True
        except Exception:
            return False

    @staticmethod
    def clone_bare(
        url: str, target_path: Path, token: str | None = None
    ) -> "BareOntologyRepository":
        """Clone a remote repo as bare with optional PAT auth."""
        callbacks = None
        if token:
            credentials = pygit2.UserPass("x-access-token", token)
            callbacks = pygit2.RemoteCallbacks(credentials=credentials)
        pygit2.clone_repository(str(url), str(target_path), bare=True, callbacks=callbacks)
        repo = BareOntologyRepository.__new__(BareOntologyRepository)
        repo.repo_path = target_path
        repo._repo = pygit2.Repository(str(target_path))
        return repo


class BareGitRepositoryService:
    """
    Service for managing bare git repositories for projects.

    This service uses bare repositories to allow concurrent access
    from multiple users working on different branches.

    Note: Bare repositories don't have a "current branch" concept.
    Methods like get_current_branch return the default branch for compatibility.
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
        # Use .git suffix for bare repos to make it clear
        return self.base_path / f"{project_id}.git"

    def get_repository(self, project_id: UUID) -> BareOntologyRepository:
        """
        Get the BareOntologyRepository for a project.

        Args:
            project_id: The project's UUID

        Returns:
            BareOntologyRepository instance for the project
        """
        repo_path = self._get_project_repo_path(project_id)
        return BareOntologyRepository(repo_path)

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
        Initialize a bare git repository for a project with the initial ontology file.

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
        repo = self.get_repository(project_id)
        message = f"Initial import of {project_name or 'ontology'}"

        return repo.write_file(
            branch_name="main",
            filepath=filename,
            content=ontology_content,
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
        branch_name: str | None = None,
    ) -> CommitInfo:
        """
        Commit changes to a branch.

        Args:
            project_id: The project's UUID
            ontology_content: The updated ontology file content
            filename: The filename to update
            message: Commit message describing the changes
            author_name: Author's display name
            author_email: Author's email address
            branch_name: Branch to commit to (defaults to active/default branch)

        Returns:
            CommitInfo for the new commit
        """
        # Use active branch if not specified
        if branch_name is None:
            branch_name = self.get_current_branch(project_id)

        repo = self.get_repository(project_id)
        return repo.write_file(
            branch_name=branch_name,
            filepath=filename,
            content=ontology_content,
            message=message,
            author_name=author_name,
            author_email=author_email,
        )

    def get_history(
        self,
        project_id: UUID,
        branch: str | None = None,
        limit: int = 50,
        all_branches: bool = True,
    ) -> list[CommitInfo]:
        """
        Get commit history for a project.

        Args:
            project_id: The project's UUID
            branch: Specific branch to get history for
            limit: Maximum number of commits to return
            all_branches: If True, include commits from all branches

        Returns:
            List of CommitInfo objects
        """
        repo = self.get_repository(project_id)
        return repo.get_history(branch=branch, limit=limit, all_branches=all_branches)

    def get_file_at_version(self, project_id: UUID, filename: str, version: str) -> str:
        """
        Get ontology file content at a specific version.

        Args:
            project_id: The project's UUID
            filename: The filename to retrieve
            version: Git commit hash or branch name

        Returns:
            File content as string
        """
        repo = self.get_repository(project_id)
        return repo.get_file_at_version(filename, version)

    def get_file_from_branch(self, project_id: UUID, branch: str, filename: str) -> bytes:
        """
        Get ontology file content from a specific branch.

        Args:
            project_id: The project's UUID
            branch: Branch name
            filename: The filename to retrieve

        Returns:
            File content as bytes
        """
        repo = self.get_repository(project_id)
        return repo.read_file(branch, filename)

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

    def get_default_branch(self, project_id: UUID) -> str:
        """Get the default branch for a project."""
        repo = self.get_repository(project_id)
        return repo.get_default_branch()

    def get_current_branch(self, project_id: UUID) -> str:
        """
        Get the current branch for a project by reading HEAD.
        """
        repo = self.get_repository(project_id)
        return repo.get_current_branch()

    def switch_branch(self, project_id: UUID, name: str) -> BranchInfo:
        """
        Validate that a branch exists and return its info.

        Note: This no longer mutates HEAD. Branch tracking is now
        handled client-side, with the branch name passed explicitly
        in API calls.

        Args:
            project_id: The project's UUID
            name: Name of the branch to validate

        Returns:
            BranchInfo for the requested branch
        """
        repo = self.get_repository(project_id)

        # Verify branch exists
        branch_ref = f"refs/heads/{name}"
        if branch_ref not in repo.repo.references:
            raise KeyError(f"Branch not found: {name}")

        # Return branch info without mutating HEAD
        branches = repo.list_branches()
        for b in branches:
            if b.name == name:
                return BranchInfo(
                    name=b.name,
                    is_current=b.is_current,
                    is_default=b.is_default,
                    commit_hash=b.commit_hash,
                    commit_message=b.commit_message,
                    commit_date=b.commit_date,
                    commits_ahead=b.commits_ahead,
                    commits_behind=b.commits_behind,
                )

        raise KeyError(f"Branch not found: {name}")

    def list_branches(self, project_id: UUID) -> list[BranchInfo]:
        """List all branches for a project."""
        repo = self.get_repository(project_id)
        return repo.list_branches()

    def create_branch(self, project_id: UUID, name: str, from_ref: str = "HEAD") -> BranchInfo:
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

    def delete_branch(self, project_id: UUID, name: str, force: bool = False) -> bool:
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

    # Remote operations

    def setup_remote(self, project_id: UUID, remote_url: str, remote_name: str = "origin") -> bool:
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
        token: str | None = None,
    ) -> bool:
        """
        Push a branch to remote.

        Args:
            project_id: The project's UUID
            branch_name: Branch to push (defaults to default branch)
            remote: Name of the remote
            force: Force push
            token: GitHub PAT for authentication

        Returns:
            True if push was successful
        """
        repo = self.get_repository(project_id)
        return repo.push(remote, branch_name, force, token=token)

    def fetch_remote(
        self, project_id: UUID, remote: str = "origin", token: str | None = None
    ) -> bool:
        """
        Fetch from remote.

        Args:
            project_id: The project's UUID
            remote: Name of the remote
            token: GitHub PAT for authentication

        Returns:
            True if fetch was successful
        """
        repo = self.get_repository(project_id)
        return repo.fetch(remote, token=token)

    def clone_from_github(
        self, project_id: UUID, repo_url: str, token: str | None = None
    ) -> BareOntologyRepository:
        """Clone a GitHub repo as bare. BLOCKING I/O — wrap in asyncio.to_thread().

        Args:
            project_id: The project's UUID
            repo_url: Clone URL of the GitHub repository
            token: GitHub PAT for authentication

        Returns:
            BareOntologyRepository for the cloned repo

        Raises:
            ValueError: If repository already exists for this project
        """
        repo_path = self._get_project_repo_path(project_id)
        if repo_path.exists():
            raise ValueError(f"Repository already exists for project {project_id}")
        return BareOntologyRepository.clone_bare(repo_url, repo_path, token)

    def list_remotes(self, project_id: UUID) -> list[dict[str, str]]:
        """List all remotes for a project."""
        repo = self.get_repository(project_id)
        return repo.list_remotes()


def get_bare_git_service() -> BareGitRepositoryService:
    """Factory function for dependency injection."""
    return BareGitRepositoryService()


def _find_ontology_iri(graph: Graph) -> str | None:
    """Find the ontology IRI (subject of rdf:type owl:Ontology) for @base."""
    from rdflib.namespace import OWL, RDF

    for subject in graph.subjects(RDF.type, OWL.Ontology):
        if isinstance(subject, URIRef):
            return str(subject)
    return None


def serialize_deterministic(graph: Graph) -> str:
    """
    Serialize graph to Turtle with deterministic triple ordering.

    This ensures consistent diffs in version control.
    """
    base = _find_ontology_iri(graph)
    iso_graph = to_isomorphic(graph)
    return iso_graph.serialize(format="turtle", base=base)


def semantic_diff(old_graph: Graph, new_graph: Graph) -> dict[str, Any]:
    """
    Compute semantic diff between two graphs.

    Returns added/removed triples regardless of serialization order.
    """
    in_both, in_old, in_new = graph_diff(old_graph, new_graph)

    return {
        "added": [{"subject": str(s), "predicate": str(p), "object": str(o)} for s, p, o in in_new],
        "removed": [
            {"subject": str(s), "predicate": str(p), "object": str(o)} for s, p, o in in_old
        ],
        "added_count": len(in_new),
        "removed_count": len(in_old),
        "unchanged_count": len(in_both),
    }
