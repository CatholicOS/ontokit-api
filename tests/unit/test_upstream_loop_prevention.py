"""Tests for upstream sync loop prevention logic."""

from typing import Any

from ontokit.core.constants import (
    ONTOKIT_COMMITTER_EMAIL,
    ONTOKIT_COMMITTER_EMAILS,
    ONTOKIT_SYNC_COMMITTER_EMAIL,
)


def _make_commit(
    email: str,
    added: list[str] | None = None,
    modified: list[str] | None = None,
) -> dict[str, Any]:
    """Create a minimal GitHub webhook commit payload."""
    return {
        "id": "abc123",
        "committer": {"name": "Test", "email": email},
        "added": added or [],
        "modified": modified or [],
    }


def _filter_external(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce the filtering logic from the webhook handler."""
    return [
        c for c in commits if c.get("committer", {}).get("email") not in ONTOKIT_COMMITTER_EMAILS
    ]


class TestCommitterEmailConstants:
    """Verify identity constants are correctly defined."""

    def test_ontokit_emails_in_set(self) -> None:
        assert ONTOKIT_COMMITTER_EMAIL in ONTOKIT_COMMITTER_EMAILS
        assert ONTOKIT_SYNC_COMMITTER_EMAIL in ONTOKIT_COMMITTER_EMAILS

    def test_set_is_frozen(self) -> None:
        assert isinstance(ONTOKIT_COMMITTER_EMAILS, frozenset)


class TestWebhookCommitFiltering:
    """Test the commit filtering logic used in the push webhook handler."""

    def test_all_ontokit_commits_filtered(self) -> None:
        """Push with only OntoKit commits → no external commits → skip sync."""
        commits = [
            _make_commit(ONTOKIT_COMMITTER_EMAIL, modified=["ontology.ttl"]),
            _make_commit(ONTOKIT_SYNC_COMMITTER_EMAIL, modified=["ontology.ttl"]),
        ]
        assert _filter_external(commits) == []

    def test_external_commits_pass_through(self) -> None:
        """Push with external commits → they pass through the filter."""
        commits = [
            _make_commit("dev@example.com", modified=["ontology.ttl"]),
        ]
        result = _filter_external(commits)
        assert len(result) == 1
        assert result[0]["committer"]["email"] == "dev@example.com"

    def test_mixed_commits_only_keep_external(self) -> None:
        """Push with both OntoKit and external commits → only external kept."""
        commits = [
            _make_commit(ONTOKIT_SYNC_COMMITTER_EMAIL, modified=["ontology.ttl"]),
            _make_commit("ci-bot@corp.com", modified=["ontology.ttl"]),
            _make_commit(ONTOKIT_COMMITTER_EMAIL, modified=["README.md"]),
        ]
        result = _filter_external(commits)
        assert len(result) == 1
        assert result[0]["committer"]["email"] == "ci-bot@corp.com"

    def test_empty_commits_list(self) -> None:
        """Empty push payload → no external commits."""
        assert _filter_external([]) == []

    def test_commit_without_committer_field(self) -> None:
        """Malformed commit without committer → treated as external (safe default)."""
        commits = [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}]
        result = _filter_external(commits)
        assert len(result) == 1

    def test_file_touch_detection_uses_only_external(self) -> None:
        """Only external commits' file lists should matter for triggering sync."""
        ontokit_commit = _make_commit(ONTOKIT_SYNC_COMMITTER_EMAIL, modified=["ontology.ttl"])
        external_commit = _make_commit("dev@example.com", modified=["README.md"])

        external = _filter_external([ontokit_commit, external_commit])

        # Collect touched files from external commits only
        touched: set[str] = set()
        for c in external:
            touched.update(c.get("added", []))
            touched.update(c.get("modified", []))

        # ontology.ttl was only touched by the OntoKit commit, not external
        assert "ontology.ttl" not in touched
        assert "README.md" in touched
