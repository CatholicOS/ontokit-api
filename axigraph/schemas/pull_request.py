"""Pull request, review, comment, branch, and GitHub integration schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Status types
PRStatusType = Literal["open", "merged", "closed"]
ReviewStatusType = Literal["approved", "changes_requested", "commented"]


# User info for responses
class PRUser(BaseModel):
    """User information for PR responses."""

    id: str
    name: str | None = None
    email: str | None = None


# Pull Request Schemas


class PRBase(BaseModel):
    """Base pull request fields."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None


class PRCreate(PRBase):
    """Schema for creating a pull request."""

    source_branch: str = Field(..., min_length=1, max_length=255)
    target_branch: str = Field(default="main", min_length=1, max_length=255)


class PRUpdate(BaseModel):
    """Schema for updating a pull request."""

    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None


class PRResponse(PRBase):
    """Schema for pull request responses."""

    id: UUID
    project_id: UUID
    pr_number: int
    source_branch: str
    target_branch: str
    status: PRStatusType
    author_id: str
    author: PRUser | None = None
    github_pr_number: int | None = None
    github_pr_url: str | None = None
    merged_by: str | None = None
    merged_by_user: PRUser | None = None
    merged_at: datetime | None = None
    merge_commit_hash: str | None = None
    base_commit_hash: str | None = None
    head_commit_hash: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    review_count: int = 0
    approval_count: int = 0
    comment_count: int = 0
    commits_ahead: int = 0
    can_merge: bool = False

    class Config:
        from_attributes = True


class PRListResponse(BaseModel):
    """Paginated list of pull requests."""

    items: list[PRResponse]
    total: int
    skip: int
    limit: int


class PRMergeRequest(BaseModel):
    """Schema for merge request body."""

    merge_message: str | None = Field(None, description="Custom merge commit message")
    delete_source_branch: bool = Field(
        default=False, description="Delete source branch after merge"
    )


class PRMergeResponse(BaseModel):
    """Schema for merge response."""

    success: bool
    message: str
    merged_at: datetime | None = None
    merge_commit_hash: str | None = None


# Review Schemas


class ReviewCreate(BaseModel):
    """Schema for creating a review."""

    status: ReviewStatusType
    body: str | None = None


class ReviewResponse(BaseModel):
    """Schema for review responses."""

    id: UUID
    pull_request_id: UUID
    reviewer_id: str
    reviewer: PRUser | None = None
    status: ReviewStatusType
    body: str | None = None
    github_review_id: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewListResponse(BaseModel):
    """List of reviews for a pull request."""

    items: list[ReviewResponse]
    total: int


# Comment Schemas


class CommentBase(BaseModel):
    """Base comment fields."""

    body: str = Field(..., min_length=1)


class CommentCreate(CommentBase):
    """Schema for creating a comment."""

    parent_id: UUID | None = Field(None, description="Parent comment ID for replies")


class CommentUpdate(BaseModel):
    """Schema for updating a comment."""

    body: str = Field(..., min_length=1)


class CommentResponse(CommentBase):
    """Schema for comment responses."""

    id: UUID
    pull_request_id: UUID
    author_id: str
    author: PRUser | None = None
    parent_id: UUID | None = None
    github_comment_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None
    replies: list["CommentResponse"] = []

    class Config:
        from_attributes = True


class CommentListResponse(BaseModel):
    """List of comments for a pull request."""

    items: list[CommentResponse]
    total: int


# Branch Schemas


class BranchInfo(BaseModel):
    """Information about a git branch."""

    name: str
    is_current: bool = False
    is_default: bool = False
    commit_hash: str | None = None
    commit_message: str | None = None
    commit_date: datetime | None = None
    commits_ahead: int = 0
    commits_behind: int = 0


class BranchListResponse(BaseModel):
    """List of branches for a project."""

    items: list[BranchInfo]
    current_branch: str
    default_branch: str


class BranchCreate(BaseModel):
    """Schema for creating a new branch."""

    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9/_-]+$")
    from_branch: str | None = Field(
        None, description="Base branch to create from (defaults to current branch)"
    )


class BranchSwitchRequest(BaseModel):
    """Schema for switching branches."""

    branch_name: str = Field(..., min_length=1, max_length=255)


class BranchDeleteRequest(BaseModel):
    """Schema for deleting a branch."""

    force: bool = Field(
        default=False, description="Force delete even if branch has unmerged changes"
    )


# GitHub Integration Schemas


class GitHubIntegrationCreate(BaseModel):
    """Schema for creating GitHub integration."""

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    webhooks_enabled: bool = False
    ontology_file_path: str | None = Field(None, max_length=500)
    turtle_file_path: str | None = Field(None, max_length=500)


class GitHubIntegrationUpdate(BaseModel):
    """Schema for updating GitHub integration."""

    default_branch: str | None = Field(None, min_length=1, max_length=255)
    sync_enabled: bool | None = None
    webhooks_enabled: bool | None = None
    ontology_file_path: str | None = Field(None, max_length=500)
    turtle_file_path: str | None = Field(None, max_length=500)


class GitHubIntegrationResponse(BaseModel):
    """Schema for GitHub integration responses."""

    id: UUID
    project_id: UUID
    repo_owner: str
    repo_name: str
    repo_url: str | None = None
    connected_by_user_id: str | None = None
    webhooks_enabled: bool = False
    default_branch: str
    ontology_file_path: str | None = None
    turtle_file_path: str | None = None
    sync_enabled: bool
    sync_status: str = "idle"
    sync_error: str | None = None
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True

    @property
    def computed_repo_url(self) -> str:
        """Compute the full GitHub repository URL."""
        return f"https://github.com/{self.repo_owner}/{self.repo_name}"


# Project PR Settings Schemas


class PRSettingsUpdate(BaseModel):
    """Schema for updating PR workflow settings."""

    pr_approval_required: int = Field(
        ...,
        ge=0,
        description="Minimum approvals required before merge (0 = no approval needed)",
    )


class PRSettingsResponse(BaseModel):
    """Schema for PR workflow settings response."""

    pr_approval_required: int
    github_integration: GitHubIntegrationResponse | None = None


# Webhook Schemas


class GitHubWebhookPayload(BaseModel):
    """Base schema for GitHub webhook payloads."""

    action: str
    repository: dict | None = None
    sender: dict | None = None


class GitHubPRWebhookPayload(GitHubWebhookPayload):
    """Schema for GitHub pull_request webhook payloads."""

    number: int
    pull_request: dict


class GitHubReviewWebhookPayload(GitHubWebhookPayload):
    """Schema for GitHub pull_request_review webhook payloads."""

    review: dict
    pull_request: dict


class GitHubPushWebhookPayload(GitHubWebhookPayload):
    """Schema for GitHub push webhook payloads."""

    ref: str
    before: str
    after: str
    commits: list[dict] = []


# Commit Schemas (for PR commit list)


class PRCommit(BaseModel):
    """Information about a commit in a pull request."""

    hash: str
    short_hash: str
    message: str
    author_name: str
    author_email: str
    timestamp: datetime


class PRCommitListResponse(BaseModel):
    """List of commits in a pull request."""

    items: list[PRCommit]
    total: int


# File Change Schemas (for PR diff)


class PRFileChange(BaseModel):
    """Information about a file change in a pull request."""

    path: str
    change_type: Literal["added", "modified", "deleted", "renamed"]
    old_path: str | None = None  # For renamed files
    additions: int = 0
    deletions: int = 0
    patch: str | None = None  # The actual diff content


class PRDiffResponse(BaseModel):
    """Diff for a pull request."""

    files: list[PRFileChange]
    total_additions: int
    total_deletions: int
    files_changed: int


# Triple change for semantic diff


class TripleChange(BaseModel):
    """A single RDF triple change."""

    subject: str
    predicate: str
    object: str
    change_type: Literal["added", "removed"]


class SemanticDiffResponse(BaseModel):
    """Semantic diff showing triple changes."""

    added: list[TripleChange]
    removed: list[TripleChange]
    total_added: int
    total_removed: int


# GitHub project creation schemas


class ProjectCreateFromGitHub(BaseModel):
    """Schema for creating a project from a GitHub repository."""

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    ontology_file_path: str = Field(..., min_length=1, max_length=500)
    turtle_file_path: str | None = Field(None, max_length=500)
    is_public: bool = False
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    default_branch: str | None = None


class GitHubRepoFileInfo(BaseModel):
    """Information about a file in a GitHub repository."""

    path: str
    name: str
    size: int


class GitHubRepoFilesResponse(BaseModel):
    """Response containing ontology files found in a GitHub repository."""

    items: list[GitHubRepoFileInfo]
    total: int


# Open PR Summary Schemas (for notification bell)


class ProjectOpenPRCount(BaseModel):
    """Count of open PRs for a single project."""

    project_id: UUID
    project_name: str
    open_count: int


class OpenPRsSummary(BaseModel):
    """Summary of open pull requests across projects the user manages."""

    total_open: int
    by_project: list[ProjectOpenPRCount]
