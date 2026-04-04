"""HMAC-based anonymous session token for unauthenticated suggestion workflows.

Anonymous tokens are long-lived, session-scoped tokens that allow
unauthenticated users to save and submit suggestion sessions without
needing a Bearer token. They are used when AUTH_MODE is "optional" or "disabled".
"""

import base64
import hashlib
import hmac
import json
import time

from ontokit.core.config import settings

_INSECURE_DEFAULTS = {"change-me-in-production", ""}
_MIN_SECRET_LENGTH = 16

# Prefix added to HMAC input to prevent token type confusion with beacon tokens
_HMAC_PREFIX = "anon:"


def _check_secret_key() -> None:
    """Raise if secret_key is an insecure placeholder or too short."""
    key = settings.secret_key
    if key in _INSECURE_DEFAULTS or len(key) < _MIN_SECRET_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is not configured securely. "
            "Set a strong, random SECRET_KEY (>= 16 characters) before using anonymous tokens."
        )


def create_anonymous_token(session_id: str, ttl: int = 86400) -> str:
    """Create an HMAC-signed anonymous session token.

    Args:
        session_id: The suggestion session ID to scope the token to.
        ttl: Time-to-live in seconds (default 24 hours).

    Returns:
        Base64url-encoded token string.
    """
    _check_secret_key()
    if ttl <= 0:
        raise ValueError("ttl must be a positive number of seconds")
    payload = json.dumps({"sid": session_id, "exp": int(time.time()) + ttl})
    # Prepend "anon:" to differentiate from beacon tokens using the same secret
    sig = hmac.new(
        settings.secret_key.encode(), (_HMAC_PREFIX + payload).encode(), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def verify_anonymous_token(token: str) -> str | None:
    """Verify an anonymous session token and return the session_id if valid.

    Args:
        token: The base64url-encoded token string.

    Returns:
        The session_id if the token is valid and not expired, None otherwise.
    """
    _check_secret_key()
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload_str, sig = decoded.rsplit("|", 1)
        expected = hmac.new(
            settings.secret_key.encode(),
            (_HMAC_PREFIX + payload_str).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(payload_str)
        if not isinstance(payload, dict):
            return None
        exp = payload.get("exp")
        sid = payload.get("sid")
        if not isinstance(exp, (int, float)) or not isinstance(sid, str):
            return None
        if time.time() > exp:
            return None
        return sid
    except Exception:
        return None
