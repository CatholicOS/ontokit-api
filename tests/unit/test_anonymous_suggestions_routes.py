"""Endpoint + guard tests for the anonymous suggestion routes (PR-7).

The lineage shipped these endpoints without tests. Coverage here pins:
- the AUTH_MODE gate (403 everywhere when auth is required),
- X-Anonymous-Token verification (401 on garbage),
- token→session binding at the routes that delegate it to the service,
- the honeypot silent-fake-success path (no service call),
- the PR-7 beacon fix (route passes the VERIFIED session id to
  beacon_save_anonymous — the lineage passed data.session_id where a beacon
  token was expected, so the endpoint always 401'd),
- the service-level public-project gate and anonymous-beacon binding.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ontokit.core.anonymous_token import create_anonymous_token
from ontokit.schemas.suggestion import SuggestionBeaconRequest

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
BASE = f"/api/v1/projects/{PROJECT_ID}/suggestions/anonymous"

SAVE_BODY = {
    "content": "ex:Foo a owl:Class .",
    "entity_iri": "http://example.org/ont#Foo",
    "entity_label": "Foo",
}
SUBMIT_BODY = {"summary": "adds Foo"}


@pytest.fixture(autouse=True)
def _secure_test_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep route tests independent of the intentionally insecure config default."""
    test_settings = type("Settings", (), {"secret_key": "test-secret-key-long-enough"})()
    monkeypatch.setattr("ontokit.core.anonymous_token.settings", test_settings)


# ── AUTH_MODE gate ────────────────────────────────────────────────────────────


def test_all_endpoints_403_when_auth_mode_required(client: TestClient) -> None:
    with patch(
        "ontokit.api.routes.anonymous_suggestions.settings"
    ) as settings_mock:
        settings_mock.auth_mode = "required"
        token = "irrelevant"
        responses = [
            client.post(f"{BASE}/sessions"),
            client.put(f"{BASE}/sessions/s_x/save", json=SAVE_BODY, headers={"X-Anonymous-Token": token}),
            client.post(f"{BASE}/sessions/s_x/submit", json=SUBMIT_BODY, headers={"X-Anonymous-Token": token}),
            client.post(f"{BASE}/sessions/s_x/discard", headers={"X-Anonymous-Token": token}),
            client.post(f"{BASE}/beacon?token={token}", json={"session_id": "s_x", "content": "x"}),
        ]
    assert [r.status_code for r in responses] == [403] * 5


# ── Token verification ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,url_suffix,kwargs",
    [
        ("put", "/sessions/s_x/save", {"json": SAVE_BODY}),
        ("post", "/sessions/s_x/submit", {"json": SUBMIT_BODY}),
        ("post", "/sessions/s_x/discard", {}),
    ],
)
def test_garbage_token_401(client: TestClient, method: str, url_suffix: str, kwargs: dict) -> None:
    with patch("ontokit.api.routes.anonymous_suggestions.settings") as settings_mock:
        settings_mock.auth_mode = "optional"
        resp = getattr(client, method)(
            f"{BASE}{url_suffix}", headers={"X-Anonymous-Token": "not-a-token"}, **kwargs
        )
    assert resp.status_code == 401


def test_beacon_garbage_token_401(client: TestClient) -> None:
    with patch("ontokit.api.routes.anonymous_suggestions.settings") as settings_mock:
        settings_mock.auth_mode = "optional"
        resp = client.post(
            f"{BASE}/beacon?token=not-a-token",
            json={"session_id": "s_x", "content": "x"},
        )
    assert resp.status_code == 401


# ── Verified-session forwarding (PR-7 beacon fix) ─────────────────────────────


def test_beacon_forwards_verified_session_id(client: TestClient) -> None:
    token = create_anonymous_token("s_abc")
    service = MagicMock()
    service.beacon_save_anonymous = AsyncMock(return_value=None)
    with (
        patch("ontokit.api.routes.anonymous_suggestions.settings") as settings_mock,
        patch(
            "ontokit.api.routes.anonymous_suggestions.get_suggestion_service",
            return_value=service,
        ),
    ):
        settings_mock.auth_mode = "optional"
        resp = client.post(
            f"{BASE}/beacon?token={token}",
            json={"session_id": "s_abc", "content": "x"},
        )
    assert resp.status_code == 204
    service.beacon_save_anonymous.assert_awaited_once()
    # third positional arg / kwarg is the VERIFIED session id from the token
    call = service.beacon_save_anonymous.await_args
    forwarded = call.args[2] if len(call.args) > 2 else call.kwargs.get("verified_session_id")
    assert forwarded == "s_abc"


def test_save_forwards_verified_session_id(client: TestClient) -> None:
    token = create_anonymous_token("s_abc")
    service = MagicMock()
    service.save_anonymous = AsyncMock(
        return_value={"commit_hash": "deadbeef", "branch": "b", "changes_count": 1}
    )
    with (
        patch("ontokit.api.routes.anonymous_suggestions.settings") as settings_mock,
        patch(
            "ontokit.api.routes.anonymous_suggestions.get_suggestion_service",
            return_value=service,
        ),
    ):
        settings_mock.auth_mode = "optional"
        resp = client.put(
            f"{BASE}/sessions/s_other/save",
            json=SAVE_BODY,
            headers={"X-Anonymous-Token": token},
        )
    assert resp.status_code == 200
    args = service.save_anonymous.await_args.args
    assert args[-1] == "s_abc"  # verified id travels separately from the path id


# ── Honeypot ──────────────────────────────────────────────────────────────────


def test_submit_honeypot_fake_success_without_service_call(client: TestClient) -> None:
    token = create_anonymous_token("s_abc")
    service = MagicMock()
    service.submit_anonymous = AsyncMock()
    with (
        patch("ontokit.api.routes.anonymous_suggestions.settings") as settings_mock,
        patch(
            "ontokit.api.routes.anonymous_suggestions.get_suggestion_service",
            return_value=service,
        ),
    ):
        settings_mock.auth_mode = "optional"
        resp = client.post(
            f"{BASE}/sessions/s_abc/submit",
            json={**SUBMIT_BODY, "website": "http://spam.example"},
            headers={"X-Anonymous-Token": token},
        )
    assert resp.status_code == 200
    assert resp.json()["pr_number"] == 0
    service.submit_anonymous.assert_not_awaited()


# ── Service-level guards (PR-7 hardening) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_create_anonymous_session_rejects_private_project() -> None:
    from ontokit.services.suggestion_service import SuggestionService

    service = SuggestionService.__new__(SuggestionService)
    private_project = MagicMock()
    private_project.is_public = False
    service._get_project = AsyncMock(return_value=private_project)  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc:
        await service.create_anonymous_session(uuid4(), "1.2.3.4")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_beacon_save_anonymous_rejects_session_mismatch() -> None:
    from ontokit.services.suggestion_service import SuggestionService

    service = SuggestionService.__new__(SuggestionService)
    data = SuggestionBeaconRequest(session_id="s_other", content="x")

    with pytest.raises(HTTPException) as exc:
        await service.beacon_save_anonymous(uuid4(), data, "s_abc")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_beacon_save_anonymous_rejects_authenticated_session() -> None:
    """An anonymous token must never flush an authenticated user's session."""
    from ontokit.services.suggestion_service import SuggestionService

    service = SuggestionService.__new__(SuggestionService)
    authed_session = MagicMock()
    authed_session.is_anonymous = False
    service._get_session = AsyncMock(return_value=authed_session)  # type: ignore[method-assign]
    data = SuggestionBeaconRequest(session_id="s_abc", content="x")

    with pytest.raises(HTTPException) as exc:
        await service.beacon_save_anonymous(uuid4(), data, "s_abc")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reap_deletes_branch_and_discards() -> None:
    """The anonymous reaper must delete the git branch (orphaned-branch leak fix)."""
    from ontokit.services.suggestion_service import SuggestionService

    service = SuggestionService.__new__(SuggestionService)
    stale = MagicMock()
    stale.id = uuid4()
    stale.project_id = uuid4()
    stale.session_id = "s_stale"
    stale.branch = "suggest/anonymous/s_stale"
    stale.changes_count = 0

    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = [stale]
    claim_result = MagicMock()
    claim_result.rowcount = 1

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, claim_result])
    db.commit = AsyncMock()
    service.db = db
    service.git_service = MagicMock()

    count = await service.reap_stale_anonymous_sessions()

    assert count == 1
    service.git_service.delete_branch.assert_called_once_with(
        stale.project_id, stale.branch, force=True
    )


@pytest.mark.asyncio
async def test_reap_skips_sessions_claimed_by_another_worker() -> None:
    from ontokit.services.suggestion_service import SuggestionService

    service = SuggestionService.__new__(SuggestionService)
    stale = MagicMock()
    stale.id = uuid4()

    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = [stale]
    claim_result = MagicMock()
    claim_result.rowcount = 0  # another worker won the claim

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[select_result, claim_result])
    db.commit = AsyncMock()
    service.db = db
    service.git_service = MagicMock()

    count = await service.reap_stale_anonymous_sessions()

    assert count == 0
    service.git_service.delete_branch.assert_not_called()


def test_openapi_does_not_disclose_honeypot_semantics() -> None:
    """The honeypot only works if the public schema doesn't explain it."""
    import json

    from ontokit.main import app

    schema = app.openapi()
    request_schema = schema["components"]["schemas"]["AnonymousSubmitRequest"]
    blob = json.dumps(request_schema) + json.dumps(
        {p: ops for p, ops in schema["paths"].items() if "anonymous" in p}
    )
    for needle in ("honeypot", "Honeypot", "bots", "bot detection", "fake success"):
        assert needle not in blob, f"OpenAPI leaks honeypot semantics via {needle!r}"
    # the field itself must still be present under its innocuous alias
    assert "website" in request_schema["properties"]
