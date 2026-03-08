"""HMAC-based beacon token for sendBeacon authentication.

Beacon tokens are short-lived, session-scoped tokens that allow
the frontend to flush unsaved drafts via navigator.sendBeacon()
without needing an Authorization header.
"""

import base64
import hashlib
import hmac
import json
import time

from ontokit.core.config import settings


def create_beacon_token(session_id: str, ttl: int = 7200) -> str:
    """Create an HMAC-signed beacon token.

    Args:
        session_id: The suggestion session ID to scope the token to.
        ttl: Time-to-live in seconds (default 2 hours).

    Returns:
        Base64url-encoded token string.
    """
    payload = json.dumps({"sid": session_id, "exp": int(time.time()) + ttl})
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def verify_beacon_token(token: str) -> str | None:
    """Verify a beacon token and return the session_id if valid.

    Args:
        token: The base64url-encoded token string.

    Returns:
        The session_id if the token is valid and not expired, None otherwise.
    """
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload_str, sig = decoded.rsplit("|", 1)
        expected = hmac.new(
            settings.secret_key.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(payload_str)
        if time.time() > payload["exp"]:
            return None
        return payload["sid"]
    except Exception:
        return None
