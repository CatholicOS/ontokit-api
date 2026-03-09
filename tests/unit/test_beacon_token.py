"""Tests for HMAC-based beacon token create/verify (ontokit/core/beacon_token.py)."""

import time

import pytest

from ontokit.core.beacon_token import create_beacon_token, verify_beacon_token


@pytest.fixture(autouse=True)
def _secure_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a secure secret key is set for all tests."""
    monkeypatch.setattr(
        "ontokit.core.beacon_token.settings",
        type("S", (), {"secret_key": "test-secret-key-long-enough"})(),
    )


def test_create_beacon_token_success() -> None:
    token = create_beacon_token("session-abc", ttl=3600)
    assert isinstance(token, str)
    assert len(token) > 0


def test_verify_beacon_token_success() -> None:
    token = create_beacon_token("session-xyz", ttl=3600)
    result = verify_beacon_token(token)
    assert result == "session-xyz"


def test_verify_beacon_token_expired() -> None:
    token = create_beacon_token("session-exp", ttl=1)
    # Simulate expiry by patching time
    original_time = time.time
    try:
        time.time = lambda: original_time() + 10  # type: ignore[assignment]
        assert verify_beacon_token(token) is None
    finally:
        time.time = original_time  # type: ignore[assignment]


def test_verify_beacon_token_invalid() -> None:
    assert verify_beacon_token("not-a-valid-token!!!") is None


def test_create_beacon_token_negative_ttl() -> None:
    with pytest.raises(ValueError, match="positive"):
        create_beacon_token("session-neg", ttl=-5)


def test_create_beacon_token_zero_ttl() -> None:
    with pytest.raises(ValueError, match="positive"):
        create_beacon_token("session-zero", ttl=0)


def test_check_secret_key_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ontokit.core.beacon_token.settings",
        type("S", (), {"secret_key": "change-me-in-production"})(),
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_beacon_token("session-bad")


def test_check_secret_key_too_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ontokit.core.beacon_token.settings",
        type("S", (), {"secret_key": "short"})(),
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_beacon_token("session-short")
