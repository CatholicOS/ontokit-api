"""GitHub integration service using Personal Access Token authentication."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


@dataclass
class GitHubPR:
    """GitHub pull request information."""

    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    head_ref: str
    base_ref: str
    user_login: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None
    merged: bool = False


@dataclass
class GitHubReview:
    """GitHub pull request review information."""

    id: int
    user_login: str
    state: str
    body: str | None
    submitted_at: datetime


@dataclass
class GitHubComment:
    """GitHub comment information."""

    id: int
    user_login: str
    body: str
    created_at: datetime
    updated_at: datetime


class GitHubService:
    """
    Service for interacting with GitHub API using Personal Access Tokens.

    All methods accept a PAT directly for authentication.
    """

    GITHUB_API_BASE = "https://api.github.com"

    async def _request(
        self,
        method: str,
        endpoint: str,
        token: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Make an authenticated request to the GitHub API.

        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            token: GitHub Personal Access Token
            data: Request body data

        Returns:
            JSON response data
        """
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{self.GITHUB_API_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=data,
            )
            response.raise_for_status()

            if response.status_code == 204:
                return {}

            return response.json()

    # User / Token Validation

    async def get_authenticated_user(self, token: str) -> tuple[str, str]:
        """Validate a PAT and return (username, scopes).

        Args:
            token: GitHub Personal Access Token

        Returns:
            Tuple of (github_username, comma-separated scopes)
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.GITHUB_API_BASE}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            data = response.json()
            scopes = response.headers.get("x-oauth-scopes", "")
            return data["login"], scopes

    async def list_user_repos(
        self,
        token: str,
        query: str | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List repositories accessible to the authenticated user.

        Args:
            token: GitHub Personal Access Token
            query: Optional search query to filter repos
            page: Page number
            per_page: Results per page

        Returns:
            List of repository info dicts
        """
        if query:
            # Use search API to find repos matching query
            endpoint = f"/search/repositories?q={query}+fork:true&sort=updated&per_page={per_page}&page={page}"
            result = await self._request("GET", endpoint, token)
            return result.get("items", []) if isinstance(result, dict) else []
        else:
            endpoint = (
                f"/user/repos?sort=updated&per_page={per_page}&page={page}"
                "&affiliation=owner,collaborator,organization_member"
            )
            result = await self._request("GET", endpoint, token)
            return result if isinstance(result, list) else []

    # Ontology file scanning

    ONTOLOGY_EXTENSIONS = {".ttl", ".owl", ".owx", ".rdf", ".n3", ".jsonld"}

    async def scan_ontology_files(
        self,
        token: str,
        owner: str,
        repo: str,
        ref: str | None = None,
    ) -> list[dict[str, Any]]:
        """Scan a GitHub repo for ontology files via the Git Trees API.

        Args:
            token: GitHub Personal Access Token
            owner: Repository owner
            repo: Repository name
            ref: Git ref (branch/tag/sha). Defaults to repo's default branch.

        Returns:
            List of dicts with path, name, and size for each ontology file found.
        """
        if ref is None:
            repo_info = await self._request("GET", f"/repos/{owner}/{repo}", token)
            ref = repo_info["default_branch"] if isinstance(repo_info, dict) else "main"

        data = await self._request(
            "GET", f"/repos/{owner}/{repo}/git/trees/{ref}?recursive=1", token
        )
        files: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for item in data.get("tree", []):
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                ext = ("." + path.rsplit(".", 1)[-1]).lower() if "." in path else ""
                if ext in self.ONTOLOGY_EXTENSIONS:
                    files.append(
                        {
                            "path": path,
                            "name": path.rsplit("/", 1)[-1],
                            "size": item.get("size", 0),
                        }
                    )
        return files

    async def get_file_content(
        self,
        token: str,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> bytes:
        """Download raw file content from a GitHub repo.

        Args:
            token: GitHub Personal Access Token
            owner: Repository owner
            repo: Repository name
            path: File path within the repository
            ref: Git ref (branch/tag/sha). Defaults to repo's default branch.

        Returns:
            Raw file content as bytes.
        """
        endpoint = f"/repos/{owner}/{repo}/contents/{path}"
        if ref:
            endpoint += f"?ref={ref}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.GITHUB_API_BASE}{endpoint}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.raw+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            return response.content

    async def get_repo_info(
        self,
        token: str,
        owner: str,
        repo: str,
    ) -> dict[str, Any]:
        """Get repository information including default branch.

        Args:
            token: GitHub Personal Access Token
            owner: Repository owner
            repo: Repository name

        Returns:
            Repository info dict from GitHub API.
        """
        data = await self._request("GET", f"/repos/{owner}/{repo}", token)
        return data if isinstance(data, dict) else {}

    # Pull Request Operations

    async def create_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
    ) -> GitHubPR:
        """Create a pull request on GitHub."""
        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            token,
            {"title": title, "head": head, "base": base, "body": body or ""},
        )

        return self._parse_pr(data)

    async def get_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> GitHubPR:
        """Get a pull request from GitHub."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            token,
        )

        return self._parse_pr(data)

    async def update_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
    ) -> GitHubPR:
        """Update a pull request on GitHub."""
        update_data: dict[str, Any] = {}
        if title is not None:
            update_data["title"] = title
        if body is not None:
            update_data["body"] = body
        if state is not None:
            update_data["state"] = state

        data = await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            token,
            update_data,
        )

        return self._parse_pr(data)

    async def merge_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: str | None = None,
        commit_message: str | None = None,
        merge_method: str = "merge",
    ) -> dict[str, Any]:
        """Merge a pull request on GitHub."""
        merge_data: dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            merge_data["commit_title"] = commit_title
        if commit_message:
            merge_data["commit_message"] = commit_message

        result = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
            token,
            merge_data,
        )
        return result if isinstance(result, dict) else {}

    async def close_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> GitHubPR:
        """Close a pull request without merging."""
        return await self.update_pull_request(token, owner, repo, pr_number, state="closed")

    async def reopen_pull_request(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> GitHubPR:
        """Reopen a closed pull request."""
        return await self.update_pull_request(token, owner, repo, pr_number, state="open")

    async def list_pull_requests(
        self,
        token: str,
        owner: str,
        repo: str,
        state: str = "open",
        base: str | None = None,
    ) -> list[GitHubPR]:
        """List pull requests for a repository."""
        endpoint = f"/repos/{owner}/{repo}/pulls?state={state}"
        if base:
            endpoint += f"&base={base}"

        data = await self._request("GET", endpoint, token)

        if isinstance(data, list):
            return [self._parse_pr(pr) for pr in data]
        return []

    # Review Operations

    async def create_review(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
        event: str,
        body: str | None = None,
    ) -> GitHubReview:
        """Create a review on a pull request."""
        review_data: dict[str, Any] = {"event": event}
        if body:
            review_data["body"] = body

        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            token,
            review_data,
        )

        return self._parse_review(data)

    async def list_reviews(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[GitHubReview]:
        """List reviews for a pull request."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            token,
        )

        if isinstance(data, list):
            return [self._parse_review(review) for review in data]
        return []

    # Comment Operations

    async def create_comment(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> GitHubComment:
        """Create a comment on a pull request."""
        data = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            token,
            {"body": body},
        )

        return self._parse_comment(data)

    async def list_comments(
        self,
        token: str,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[GitHubComment]:
        """List comments on a pull request."""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            token,
        )

        if isinstance(data, list):
            return [self._parse_comment(comment) for comment in data]
        return []

    # Webhook Verification

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
        """Verify a GitHub webhook signature."""
        if not signature.startswith("sha256="):
            return False

        expected_signature = signature[7:]
        computed_signature = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_signature, computed_signature)

    # Helper Methods

    def _parse_pr(self, data: dict[str, Any] | list[dict[str, Any]]) -> GitHubPR:
        """Parse GitHub PR API response to GitHubPR dataclass."""
        if isinstance(data, list):
            raise ValueError("Expected a single PR dict, got a list")

        merged_at = None
        if data.get("merged_at"):
            merged_at = datetime.fromisoformat(data["merged_at"].replace("Z", "+00:00"))

        return GitHubPR(
            number=data["number"],
            title=data["title"],
            body=data.get("body"),
            state=data["state"],
            html_url=data["html_url"],
            head_ref=data["head"]["ref"],
            base_ref=data["base"]["ref"],
            user_login=data["user"]["login"],
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
            merged_at=merged_at,
            merged=data.get("merged", False),
        )

    def _parse_review(self, data: dict[str, Any] | list[dict[str, Any]]) -> GitHubReview:
        """Parse GitHub review API response to GitHubReview dataclass."""
        if isinstance(data, list):
            raise ValueError("Expected a single review dict, got a list")

        return GitHubReview(
            id=data["id"],
            user_login=data["user"]["login"],
            state=data["state"],
            body=data.get("body"),
            submitted_at=datetime.fromisoformat(data["submitted_at"].replace("Z", "+00:00")),
        )

    def _parse_comment(self, data: dict[str, Any] | list[dict[str, Any]]) -> GitHubComment:
        """Parse GitHub comment API response to GitHubComment dataclass."""
        if isinstance(data, list):
            raise ValueError("Expected a single comment dict, got a list")

        return GitHubComment(
            id=data["id"],
            user_login=data["user"]["login"],
            body=data["body"],
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
        )


def get_github_service() -> GitHubService:
    """Factory function for dependency injection."""
    return GitHubService()
