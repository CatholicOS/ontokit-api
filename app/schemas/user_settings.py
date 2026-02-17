"""User settings schemas for GitHub token management and repo listing."""

from datetime import datetime

from pydantic import BaseModel, Field


class GitHubTokenCreate(BaseModel):
    """Schema for saving a GitHub Personal Access Token."""

    token: str = Field(..., min_length=1)


class GitHubTokenResponse(BaseModel):
    """Schema for returning stored token metadata (never the token itself)."""

    github_username: str | None = None
    token_scopes: str | None = None
    token_preview: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class GitHubTokenStatus(BaseModel):
    """Schema for checking whether the user has a stored token."""

    has_token: bool
    github_username: str | None = None


class GitHubRepoInfo(BaseModel):
    """Schema for a GitHub repository returned by the repo picker."""

    full_name: str
    owner: str
    name: str
    description: str | None = None
    private: bool = False
    default_branch: str = "main"
    html_url: str


class GitHubRepoListResponse(BaseModel):
    """Paginated list of GitHub repositories."""

    items: list[GitHubRepoInfo]
    total: int
