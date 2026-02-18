"""Git version control integration.

This module provides git operations for ontology versioning using bare repositories
for concurrent access support.
"""

# Import from the new bare repository implementation
from axigraph.git.bare_repository import (
    BareGitRepositoryService,
    BareOntologyRepository,
    BranchInfo,
    CommitInfo,
    DiffInfo,
    FileChange,
    MergeResult,
    get_bare_git_service,
    semantic_diff,
    serialize_deterministic,
)

# Backward-compatible aliases
GitRepositoryService = BareGitRepositoryService
OntologyRepository = BareOntologyRepository
get_git_service = get_bare_git_service

__all__ = [
    # New names (preferred)
    "BareGitRepositoryService",
    "BareOntologyRepository",
    "get_bare_git_service",
    # Backward-compatible aliases
    "GitRepositoryService",
    "OntologyRepository",
    "get_git_service",
    # Data classes
    "BranchInfo",
    "CommitInfo",
    "DiffInfo",
    "FileChange",
    "MergeResult",
    # Utility functions
    "semantic_diff",
    "serialize_deterministic",
]
