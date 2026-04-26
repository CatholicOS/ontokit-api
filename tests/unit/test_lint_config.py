"""Tests for per-project lint configuration (issue #26).

Covers:
- Lint level presets and get_rules_for_level()
- ProjectLintConfig model logic (get_enabled_rule_ids)
- GET / PUT /api/v1/projects/{id}/lint/config endpoints
- GET /api/v1/projects/lint/levels endpoint
- Worker integration with per-project lint config
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ontokit.models.lint_config import ProjectLintConfig
from ontokit.services.linter import (
    ALL_RULE_IDS,
    LINT_LEVELS,
    LINT_RULES,
    OntologyLinter,
    get_linter,
    get_rules_for_level,
)

PROJECT_ID = "12345678-1234-5678-1234-567812345678"


# ---------------------------------------------------------------------------
# 1. Lint level presets
# ---------------------------------------------------------------------------


class TestLintLevels:
    """Tests for progressive lint levels defined in linter.py."""

    def test_level_1_critical_rules(self) -> None:
        """Level 1 contains only critical structural rules."""
        rules = get_rules_for_level(1)
        assert rules == {"undefined-parent", "circular-hierarchy", "undefined-prefix"}

    def test_level_2_includes_level_1(self) -> None:
        """Level 2 is a superset of level 1."""
        assert get_rules_for_level(1).issubset(get_rules_for_level(2))

    def test_level_3_includes_level_2(self) -> None:
        """Level 3 is a superset of level 2."""
        assert get_rules_for_level(2).issubset(get_rules_for_level(3))

    def test_level_4_includes_level_3(self) -> None:
        """Level 4 is a superset of level 3."""
        assert get_rules_for_level(3).issubset(get_rules_for_level(4))

    def test_level_5_is_all_rules(self) -> None:
        """Level 5 contains every defined rule."""
        assert get_rules_for_level(5) == ALL_RULE_IDS

    def test_all_rule_ids_matches_lint_rules(self) -> None:
        """ALL_RULE_IDS matches the set of rule_id from LINT_RULES."""
        assert {r.rule_id for r in LINT_RULES} == ALL_RULE_IDS

    def test_invalid_level_low(self) -> None:
        """get_rules_for_level raises ValueError for level < 1."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            get_rules_for_level(0)

    def test_invalid_level_high(self) -> None:
        """get_rules_for_level raises ValueError for level > 5."""
        with pytest.raises(ValueError, match="between 1 and 5"):
            get_rules_for_level(6)

    def test_get_rules_is_immutable(self) -> None:
        """get_rules_for_level returns a frozenset so callers cannot mutate the source."""
        rules = get_rules_for_level(1)
        assert isinstance(rules, frozenset)
        with pytest.raises(AttributeError):
            rules.add("fake-rule")  # type: ignore[attr-defined]
        assert "fake-rule" not in LINT_LEVELS[1]

    def test_each_level_has_more_rules(self) -> None:
        """Each successive level has strictly more rules than the previous."""
        for lvl in range(1, 5):
            assert len(get_rules_for_level(lvl)) < len(get_rules_for_level(lvl + 1))


# ---------------------------------------------------------------------------
# 2. ProjectLintConfig model logic
# ---------------------------------------------------------------------------


class TestProjectLintConfigModel:
    """Tests for ProjectLintConfig.get_enabled_rule_ids()."""

    @staticmethod
    def _make_config(
        lint_level: int | None = None,
        enabled_rules: str | None = None,
    ) -> Mock:
        """Create a Mock that behaves like ProjectLintConfig for testing logic."""
        config = Mock(spec=ProjectLintConfig)
        config.lint_level = lint_level
        config.enabled_rules = enabled_rules
        # Use the real implementation
        config.get_enabled_rule_ids = lambda: ProjectLintConfig.get_enabled_rule_ids(config)
        return config

    def test_no_config_returns_none(self) -> None:
        """When neither lint_level nor enabled_rules is set, returns None (= all rules)."""
        config = self._make_config()
        assert config.get_enabled_rule_ids() is None

    def test_lint_level_returns_level_rules(self) -> None:
        """When lint_level is set, returns the rules for that level."""
        config = self._make_config(lint_level=2)
        result = config.get_enabled_rule_ids()
        assert result == get_rules_for_level(2)

    def test_enabled_rules_returns_valid_subset(self) -> None:
        """When enabled_rules is a comma string, returns the valid rule IDs."""
        config = self._make_config(enabled_rules="missing-label,orphan-class")
        result = config.get_enabled_rule_ids()
        assert result == {"missing-label", "orphan-class"}

    def test_enabled_rules_filters_invalid(self) -> None:
        """Invalid rule IDs in enabled_rules are filtered out."""
        config = self._make_config(enabled_rules="missing-label,bogus-rule")
        result = config.get_enabled_rule_ids()
        assert result == {"missing-label"}

    def test_lint_level_takes_precedence(self) -> None:
        """When both lint_level and enabled_rules are set, lint_level wins."""
        config = self._make_config(lint_level=1, enabled_rules="missing-label")
        result = config.get_enabled_rule_ids()
        assert result == get_rules_for_level(1)

    def test_enabled_rules_whitespace_handling(self) -> None:
        """Extra whitespace in enabled_rules is trimmed correctly."""
        config = self._make_config(enabled_rules=" missing-label , orphan-class ")
        result = config.get_enabled_rule_ids()
        assert result == {"missing-label", "orphan-class"}

    def test_empty_enabled_rules_string(self) -> None:
        """An empty enabled_rules string means explicitly 'no rules' (empty set)."""
        config = self._make_config(enabled_rules="")
        result = config.get_enabled_rule_ids()
        assert result == set()

    def test_repr(self) -> None:
        """__repr__ includes project_id and lint_level."""
        config = self._make_config(lint_level=3)
        config.project_id = PROJECT_ID
        result = ProjectLintConfig.__repr__(config)
        assert "lint_level=3" in result
        assert PROJECT_ID in result


# ---------------------------------------------------------------------------
# 3. GET /api/v1/projects/{id}/lint/config
# ---------------------------------------------------------------------------


class TestGetLintConfig:
    """Tests for GET /api/v1/projects/{id}/lint/config."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_no_config_returns_all_rules(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """When no config exists, returns all rules as effective."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/config")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == PROJECT_ID
        assert data["lint_level"] is None
        assert data["enabled_rules"] is None
        assert set(data["effective_rules"]) == ALL_RULE_IDS

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_config_with_level(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """When config has a lint_level, returns level rules as effective."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        mock_config = Mock()
        mock_config.lint_level = 2
        mock_config.enabled_rules = None
        mock_config.updated_at = now
        mock_config.get_enabled_rule_ids.return_value = get_rules_for_level(2)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/config")
        assert response.status_code == 200
        data = response.json()
        assert data["lint_level"] == 2
        assert set(data["effective_rules"]) == get_rules_for_level(2)

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_config_with_custom_rules(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """When config has enabled_rules, returns those as effective."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        mock_config = Mock()
        mock_config.lint_level = None
        mock_config.enabled_rules = "missing-label,orphan-class"
        mock_config.updated_at = now
        mock_config.get_enabled_rule_ids.return_value = {"missing-label", "orphan-class"}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/config")
        assert response.status_code == 200
        data = response.json()
        assert data["lint_level"] is None
        assert set(data["enabled_rules"]) == {"missing-label", "orphan-class"}
        assert set(data["effective_rules"]) == {"missing-label", "orphan-class"}


# ---------------------------------------------------------------------------
# 4. PUT /api/v1/projects/{id}/lint/config
# ---------------------------------------------------------------------------


class TestUpdateLintConfig:
    """Tests for PUT /api/v1/projects/{id}/lint/config."""

    @staticmethod
    def _mock_upsert_session(
        mock_session: AsyncMock,
        config_after: Mock,
    ) -> None:
        """Configure mock session for upsert flow (single execute via RETURNING + commit)."""
        upsert_result = MagicMock()
        upsert_result.scalar_one.return_value = config_after
        mock_session.execute.return_value = upsert_result

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_set_lint_level(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Setting lint_level creates/updates config and returns level rules."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        config_after = Mock()
        config_after.lint_level = 3
        config_after.enabled_rules = None
        config_after.updated_at = now
        config_after.get_enabled_rule_ids.return_value = get_rules_for_level(3)

        self._mock_upsert_session(mock_session, config_after)

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lint_level"] == 3
        assert set(data["effective_rules"]) == get_rules_for_level(3)

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_set_custom_rules(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Setting enabled_rules creates a config with those specific rules."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        config_after = Mock()
        config_after.lint_level = None
        config_after.enabled_rules = "missing-label,orphan-class"
        config_after.updated_at = now
        config_after.get_enabled_rule_ids.return_value = {"missing-label", "orphan-class"}

        self._mock_upsert_session(mock_session, config_after)

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"enabled_rules": ["missing-label", "orphan-class"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert set(data["effective_rules"]) == {"missing-label", "orphan-class"}

    def test_invalid_rule_ids_rejected(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Unknown rule IDs return 422 via Pydantic schema validation."""
        client, _ = authed_client

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"enabled_rules": ["missing-label", "totally-fake-rule"]},
        )
        assert response.status_code == 422

    def test_lint_level_and_enabled_rules_together_rejected(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Setting both lint_level and enabled_rules is contradictory and must be
        rejected. Presets are immutable, so the two modes are mutually exclusive."""
        client, _ = authed_client

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 3, "enabled_rules": ["missing-label"]},
        )
        assert response.status_code == 422
        body = response.json()
        # Confirm the error is the XOR validator, not unrelated noise.
        assert "mutually exclusive" in str(body).lower()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_update_existing_config(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Updating an existing config uses upsert and returns new state."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        config_after = Mock()
        config_after.lint_level = 4
        config_after.enabled_rules = None
        config_after.updated_at = now
        config_after.get_enabled_rule_ids.return_value = get_rules_for_level(4)

        self._mock_upsert_session(mock_session, config_after)

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 4},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lint_level"] == 4
        assert set(data["effective_rules"]) == get_rules_for_level(4)

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_reset_config(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Setting both to null resets to all rules."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        config_after = Mock()
        config_after.lint_level = None
        config_after.enabled_rules = None
        config_after.updated_at = now
        config_after.get_enabled_rule_ids.return_value = None

        self._mock_upsert_session(mock_session, config_after)

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": None, "enabled_rules": None},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["lint_level"] is None
        assert data["enabled_rules"] is None
        assert set(data["effective_rules"]) == ALL_RULE_IDS

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_set_empty_rules_disables_all(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Setting enabled_rules to empty list explicitly disables all rules."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        config_after = Mock()
        config_after.lint_level = None
        config_after.enabled_rules = ""
        config_after.updated_at = now
        config_after.get_enabled_rule_ids.return_value = set()

        self._mock_upsert_session(mock_session, config_after)

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"enabled_rules": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["effective_rules"] == []

    @patch("ontokit.api.routes.lint.get_project_service")
    def test_manage_access_forbidden_for_editor(
        self,
        mock_get_svc: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 403 when user has editor role (admin/owner required)."""
        client, mock_session = authed_client

        mock_svc = AsyncMock()
        mock_svc.get.return_value = SimpleNamespace(user_role="editor")
        mock_get_svc.return_value = mock_svc

        mock_project = Mock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 1},
        )
        assert response.status_code == 403
        assert "admin access required" in response.json()["detail"].lower()

    def test_lint_level_validation_too_low(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """lint_level < 1 is rejected by Pydantic validation."""
        client, _ = authed_client
        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 0},
        )
        assert response.status_code == 422

    def test_lint_level_validation_too_high(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """lint_level > 5 is rejected by Pydantic validation."""
        client, _ = authed_client
        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/lint/config",
            json={"lint_level": 6},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 5. GET /api/v1/projects/lint/levels
# ---------------------------------------------------------------------------


class TestGetLintLevels:
    """Tests for GET /api/v1/projects/lint/levels."""

    def test_returns_all_five_levels(self, client: TestClient) -> None:
        """Returns information about all 5 lint levels."""
        response = client.get("/api/v1/projects/lint/levels")
        assert response.status_code == 200
        data = response.json()
        assert len(data["levels"]) == 5
        levels = {lvl["level"] for lvl in data["levels"]}
        assert levels == {1, 2, 3, 4, 5}

    def test_level_info_structure(self, client: TestClient) -> None:
        """Each level has name, description, and rule_ids."""
        response = client.get("/api/v1/projects/lint/levels")
        data = response.json()
        for level in data["levels"]:
            assert "level" in level
            assert "name" in level
            assert "description" in level
            assert "rule_ids" in level
            assert isinstance(level["rule_ids"], list)
            assert len(level["rule_ids"]) > 0

    def test_level_5_has_all_rules(self, client: TestClient) -> None:
        """Level 5 includes all available rules."""
        response = client.get("/api/v1/projects/lint/levels")
        data = response.json()
        level_5 = next(lvl for lvl in data["levels"] if lvl["level"] == 5)
        assert set(level_5["rule_ids"]) == ALL_RULE_IDS


# ---------------------------------------------------------------------------
# 6. Linter integration with config
# ---------------------------------------------------------------------------


class TestLinterWithConfig:
    """Tests that the linter correctly uses per-project config."""

    async def test_linter_with_level_1_only_checks_critical(self) -> None:
        """Linter configured with level 1 rules only checks those rules."""
        rules = get_rules_for_level(1)
        linter = get_linter(enabled_rules=rules)
        assert linter.enabled_rules == rules

    async def test_linter_with_custom_subset(self) -> None:
        """Linter configured with a custom rule set only runs those."""
        from rdflib import Graph, Namespace
        from rdflib.namespace import OWL, RDF

        EX = Namespace("http://example.org/")
        g = Graph()
        g.add((EX.Lonely, RDF.type, OWL.Class))
        # This class has no label, no comment, and is orphaned

        # Only enable missing-label
        linter = OntologyLinter(enabled_rules={"missing-label"})
        issues = await linter.lint(g, uuid4())

        rule_ids = {i.rule_id for i in issues}
        assert "missing-label" in rule_ids
        assert "orphan-class" not in rule_ids
        assert "missing-comment" not in rule_ids

    async def test_empty_enabled_rules_disables_linting(self) -> None:
        """An explicit empty rule set must disable linting completely.

        End-to-end check on the path: PUT enabled_rules=[] persists "" in the
        DB → ProjectLintConfig.get_enabled_rule_ids() returns set() → worker
        passes set() to get_linter() → linter produces 0 issues.

        Without this, the empty-set semantics are only proved at the model
        layer; the worker could silently fall back to "all rules" and the
        bug wouldn't surface in unit tests.
        """
        from rdflib import Graph, Namespace
        from rdflib.namespace import OWL, RDF, RDFS

        EX = Namespace("http://example.org/")
        g = Graph()
        # A graph that would normally fire many rules: orphan, no label,
        # no comment, undefined parent, etc.
        g.add((EX.Orphan, RDF.type, OWL.Class))
        g.add((EX.Bad, RDF.type, OWL.Class))
        g.add((EX.Bad, RDFS.subClassOf, EX.UndefinedParent))

        # Simulate the resolution chain: model → set() → worker → linter
        config = ProjectLintConfig()
        config.enabled_rules = ""  # PUT with enabled_rules=[]
        config.lint_level = None
        rules = ProjectLintConfig.get_enabled_rule_ids(config)
        assert rules == set(), "model must resolve empty string to empty set"

        linter = get_linter(enabled_rules=rules)
        issues = await linter.lint(g, uuid4())
        assert issues == [], "empty rule set must produce zero issues"


# ---------------------------------------------------------------------------
# 7. Auth gating: require_manage and require_write
# ---------------------------------------------------------------------------


class TestVerifyProjectAccess:
    """Direct unit tests for verify_project_access role gating.

    Existing route tests mock verify_project_access entirely, so the new
    require_manage parameter introduced by this PR is otherwise untested.
    Editor and viewer must be rejected; admin and owner must pass.
    """

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        session = AsyncMock()
        # Project lookup returns a real-looking object
        project = SimpleNamespace(id=uuid4())
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = project
        session.execute = AsyncMock(return_value=execute_result)
        return session

    async def _call_with_role(
        self,
        mock_db: AsyncMock,
        role: str | None,
        *,
        require_manage: bool = False,
        require_write: bool = False,
    ) -> object:
        from ontokit.api.routes.lint import verify_project_access
        from ontokit.core.auth import CurrentUser

        user = CurrentUser(id="u1", email="u@example.com", name="U", username="u", roles=[])

        # Mock get_project_service to return a service whose .get yields
        # a project_response with the requested user_role.
        with patch("ontokit.api.routes.lint.get_project_service") as mock_factory:
            service = AsyncMock()
            service.get = AsyncMock(return_value=SimpleNamespace(user_role=role))
            mock_factory.return_value = service

            return await verify_project_access(
                project_id=uuid4(),
                db=mock_db,
                user=user,
                require_write=require_write,
                require_manage=require_manage,
            )

    @pytest.mark.parametrize("role", ["owner", "admin"])
    async def test_require_manage_allows_owner_and_admin(
        self, mock_db: AsyncMock, role: str
    ) -> None:
        """Owner and admin pass require_manage gating."""
        result = await self._call_with_role(mock_db, role, require_manage=True)
        assert result is not None  # returns the Project model

    @pytest.mark.parametrize("role", ["editor", "suggester", "viewer", None])
    async def test_require_manage_rejects_non_admins(
        self, mock_db: AsyncMock, role: str | None
    ) -> None:
        """Editor, suggester, viewer, and no-role users are rejected with 403."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await self._call_with_role(mock_db, role, require_manage=True)
        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    @pytest.mark.parametrize("role", ["owner", "admin", "editor"])
    async def test_require_write_allows_writers(self, mock_db: AsyncMock, role: str) -> None:
        """Owner, admin, and editor pass require_write gating."""
        result = await self._call_with_role(mock_db, role, require_write=True)
        assert result is not None

    @pytest.mark.parametrize("role", ["suggester", "viewer", None])
    async def test_require_write_rejects_non_writers(
        self, mock_db: AsyncMock, role: str | None
    ) -> None:
        """Suggester, viewer, and no-role are rejected by require_write."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await self._call_with_role(mock_db, role, require_write=True)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 8. Clear lint results endpoint
# ---------------------------------------------------------------------------


class TestClearLintResults:
    """Tests for DELETE /api/v1/projects/{id}/lint/results.

    This is a destructive admin-only endpoint that this PR introduces with
    zero coverage. We test happy-path 204 and that the auth gate is wired
    through with require_manage=True.
    """

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_clear_succeeds_for_admin(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Successful clear returns 204 and issues a DELETE on lint_runs."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/results")

        assert response.status_code == 204
        # Ensure the auth check requested manage-level access.
        assert mock_access.call_args.kwargs.get("require_manage") is True
        # Ensure a DELETE statement was executed against the DB.
        assert mock_session.execute.await_count >= 1
        mock_session.commit.assert_awaited()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_clear_propagates_403_from_auth(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """When verify_project_access raises 403, the route returns 403 and
        does not commit any deletes."""
        from fastapi import HTTPException

        client, mock_session = authed_client
        mock_access.side_effect = HTTPException(status_code=403, detail="Admin access required")

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/results")

        assert response.status_code == 403
        mock_session.commit.assert_not_awaited()

    def test_clear_requires_authentication(self) -> None:
        """Unauthenticated callers cannot clear lint results."""
        from ontokit.core.auth import get_current_user
        from ontokit.core.database import get_db
        from ontokit.main import app

        async def _no_user() -> None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")

        async def _no_db():  # type: ignore[no-untyped-def]
            yield AsyncMock()

        original_app_override_get_current_user = app.dependency_overrides.get(get_current_user)
        original_app_override_get_db = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_current_user] = _no_user
        app.dependency_overrides[get_db] = _no_db
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/results")
            assert response.status_code == 401
        finally:
            if original_app_override_get_current_user is None:
                del app.dependency_overrides[get_current_user]
            else:
                app.dependency_overrides[get_current_user] = original_app_override_get_current_user
            if original_app_override_get_db is None:
                del app.dependency_overrides[get_db]
            else:
                app.dependency_overrides[get_db] = original_app_override_get_db
