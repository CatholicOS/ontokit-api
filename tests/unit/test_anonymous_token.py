"""Unit tests for ontokit/core/anonymous_token.py (PR-7).

Pins the invariants /ce:review called out as untested:
- TTL expiry and tamper rejection,
- malformed-token handling (uniform None, no exceptions),
- the insecure-SECRET_KEY guard,
- CROSS-TOKEN REJECTION between anonymous and beacon tokens — both are HMACs
  under the same secret; the `anon:` prefix separation must hold in BOTH
  directions or a beacon token could act as a session credential (and vice
  versa).
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from ontokit.core.anonymous_token import create_anonymous_token, verify_anonymous_token
from ontokit.core.beacon_token import create_beacon_token, verify_beacon_token


def test_round_trip() -> None:
    token = create_anonymous_token("s_abc123")
    assert verify_anonymous_token(token) == "s_abc123"


def test_expired_token_rejected() -> None:
    token = create_anonymous_token("s_abc123", ttl=1)
    with patch("ontokit.core.anonymous_token.time") as time_mock:
        time_mock.time.return_value = time.time() + 10
        assert verify_anonymous_token(token) is None


def test_zero_or_negative_ttl_rejected_at_creation() -> None:
    with pytest.raises(ValueError):
        create_anonymous_token("s_abc123", ttl=0)
    with pytest.raises(ValueError):
        create_anonymous_token("s_abc123", ttl=-5)


def test_tampered_token_rejected() -> None:
    token = create_anonymous_token("s_abc123")
    # flip a character in the middle of the token
    mid = len(token) // 2
    flipped = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
    assert verify_anonymous_token(flipped) is None


@pytest.mark.parametrize(
    "garbage",
    ["", "not-base64!!!", "aGVsbG8=", "e30=", "a.b.c"],
)
def test_malformed_tokens_return_none(garbage: str) -> None:
    assert verify_anonymous_token(garbage) is None


def test_insecure_secret_key_guard() -> None:
    with patch("ontokit.core.anonymous_token.settings") as settings_mock:
        settings_mock.secret_key = "change-me-in-production"
        with pytest.raises(RuntimeError):
            create_anonymous_token("s_abc123")
    with patch("ontokit.core.anonymous_token.settings") as settings_mock:
        settings_mock.secret_key = "short"
        with pytest.raises(RuntimeError):
            create_anonymous_token("s_abc123")


# ── Cross-token confusion (anonymous vs beacon, same secret) ─────────────────


def test_beacon_token_never_verifies_as_anonymous_token() -> None:
    beacon = create_beacon_token("s_abc123")
    assert verify_anonymous_token(beacon) is None


def test_anonymous_token_never_verifies_as_beacon_token() -> None:
    anon = create_anonymous_token("s_abc123")
    assert verify_beacon_token(anon) is None
