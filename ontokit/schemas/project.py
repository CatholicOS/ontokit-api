"""Project and project member schemas."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Role type for project members
ProjectRole = Literal["owner", "admin", "editor", "suggester", "viewer"]

_IRI_PATTERN = re.compile(r"^(https?://|urn:)\S+$")


def _validate_iri(value: str) -> str:
    """Validate that a string is a well-formed IRI with a recognised scheme."""
    if not _IRI_PATTERN.match(value):
        raise ValueError(
            "Invalid IRI: must start with 'http://', 'https://', or 'urn:' "
            "and contain no whitespace"
        )
    return value


class ProjectBase(BaseModel):
    """Base project fields."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_public: bool = False


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    is_public: bool | None = None
    label_preferences: list[str] | None = Field(
        None,
        description=(
            "Label preferences for ontology display. "
            "Format: ['rdfs:label@en', 'skos:prefLabel', ...]"
        ),
    )


class ProjectOwner(BaseModel):
    """Minimal owner information for project responses."""

    id: str
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class NormalizationReportResponse(BaseModel):
    """Report of changes made during ontology normalization on import."""

    original_format: str
    original_filename: str
    original_size_bytes: int
    normalized_size_bytes: int
    triple_count: int
    prefixes_before: list[str]
    prefixes_after: list[str]
    prefixes_removed: list[str]
    prefixes_added: list[str]
    format_converted: bool
    notes: list[str]


class ProjectResponse(ProjectBase):
    """Schema for project responses."""

    id: UUID
    owner_id: str
    owner: ProjectOwner | None = None
    created_at: datetime
    updated_at: datetime | None = None
    member_count: int = 0
    user_role: ProjectRole | None = None  # Current user's role in the project
    is_superadmin: bool = False  # Whether the current user is a superadmin
    # Import-related fields (optional, only set when project was created via import)
    source_file_path: str | None = None
    git_ontology_path: str | None = None
    ontology_iri: str | None = Field(default=None, max_length=2048)
    # Label preferences for ontology display
    label_preferences: list[str] | None = None
    # Normalization report from initial import
    normalization_report: NormalizationReportResponse | None = None

    @field_validator("ontology_iri")
    @classmethod
    def ontology_iri_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iri(v)
        return v

    class Config:
        from_attributes = True


class ExtractedOntologyMetadata(BaseModel):
    """Metadata extracted from an ontology file during import."""

    ontology_iri: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    format_detected: str

    @field_validator("ontology_iri")
    @classmethod
    def ontology_iri_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iri(v)
        return v


class ProjectImportResponse(ProjectResponse):
    """Schema for project import responses."""

    ontology_iri: str | None = Field(default=None, max_length=2048)
    file_path: str

    @field_validator("ontology_iri")
    @classmethod
    def import_ontology_iri_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iri(v)
        return v


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    items: list[ProjectResponse]
    total: int
    skip: int
    limit: int


# Project Member Schemas


class MemberBase(BaseModel):
    """Base member fields."""

    user_id: str
    role: ProjectRole = "suggester"


class MemberCreate(MemberBase):
    """Schema for adding a member to a project."""

    pass


class MemberUpdate(BaseModel):
    """Schema for updating a member's role."""

    role: ProjectRole


class TransferOwnership(BaseModel):
    """Schema for transferring project ownership to another member."""

    new_owner_id: str


class MemberUser(BaseModel):
    """User information for member responses."""

    id: str
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class MemberResponse(MemberBase):
    """Schema for member responses."""

    id: UUID
    project_id: UUID
    user: MemberUser | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """List of project members."""

    items: list[MemberResponse]
    total: int


# Revision History Schemas


class RevisionCommit(BaseModel):
    """Information about a single commit/revision."""

    hash: str
    short_hash: str
    message: str = Field(..., max_length=5000)
    author_name: str = Field(..., max_length=255)
    author_email: str = Field(..., max_length=320)
    timestamp: str
    is_merge: bool = False
    merged_branch: str | None = None
    parent_hashes: list[str] = []


class RevisionHistoryResponse(BaseModel):
    """List of revisions for a project."""

    project_id: UUID
    commits: list[RevisionCommit]
    total: int


class RevisionDiffChange(BaseModel):
    """A single file change in a diff."""

    path: str
    change_type: str
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str | None = None


class RevisionDiffResponse(BaseModel):
    """Diff between two revisions."""

    project_id: UUID
    from_version: str
    to_version: str
    files_changed: int
    changes: list[RevisionDiffChange]


class RevisionFileResponse(BaseModel):
    """File content at a specific revision."""

    project_id: UUID
    version: str
    filename: str
    content: str


# Branch Schemas


class BranchInfo(BaseModel):
    """Information about a git branch."""

    name: str = Field(..., max_length=255)
    is_current: bool = False
    is_default: bool = False
    commit_hash: str | None = None
    commit_message: str | None = Field(default=None, max_length=5000)
    commit_date: datetime | None = None
    commits_ahead: int = 0
    commits_behind: int = 0
    remote_commits_ahead: int | None = None
    remote_commits_behind: int | None = None
    created_by_id: str | None = None
    created_by_name: str | None = Field(default=None, max_length=255)
    can_delete: bool = False
    has_open_pr: bool = False
    has_delete_permission: bool = False


class BranchCreate(BaseModel):
    """Schema for creating a new branch."""

    name: str = Field(..., min_length=1, max_length=255)
    from_branch: str | None = Field(
        None, description="Branch to create from (defaults to current branch)"
    )


class BranchListResponse(BaseModel):
    """List of branches for a project."""

    items: list[BranchInfo]
    current_branch: str
    default_branch: str
    preferred_branch: str | None = None
    has_github_remote: bool = False
    last_sync_at: datetime | None = None
    sync_status: str | None = None


# Source Content Schemas


class SourceContentSave(BaseModel):
    """Schema for saving ontology source content."""

    content: str = Field(..., description="The ontology source content (Turtle format)")
    commit_message: str = Field(
        ..., min_length=1, max_length=500, description="Commit message describing the changes"
    )


class SourceContentSaveResponse(BaseModel):
    """Response after saving ontology source content."""

    success: bool
    commit_hash: str
    commit_message: str
    branch: str
