"""Authentication and authorization utilities."""

import asyncio
import time
from typing import Annotated, Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from ontokit.core.config import settings

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)

# Zitadel roles claim key
ZITADEL_ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"

# JWKS cache TTL in seconds (1 hour)
_JWKS_CACHE_TTL = 3600


def _extract_roles(payload: dict[str, Any]) -> list[str]:
    """Extract role names from the Zitadel roles claim.

    The Zitadel roles claim format is:
        {"urn:zitadel:iam:org:project:roles": {"role_name": {"org_id": "org_name"}, ...}}

    This function extracts just the role names (top-level keys of the roles dict).
    """
    roles_claim = payload.get(ZITADEL_ROLES_CLAIM)
    if not roles_claim or not isinstance(roles_claim, dict):
        return []
    return list(roles_claim.keys())


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # Subject (user ID)
    exp: int  # Expiration time
    iat: int  # Issued at
    iss: str  # Issuer
    aud: list[str] | str | None = None  # Audience
    azp: str | None = None  # Authorized party (client ID)
    scope: str | None = None  # Scopes
    email: str | None = None
    name: str | None = None
    preferred_username: str | None = None
    roles: list[str] = Field(default_factory=list)  # Extracted from Zitadel roles claim


class CurrentUser(BaseModel):
    """Current authenticated user."""

    id: str
    email: str | None = None
    name: str | None = None
    username: str | None = None
    roles: list[str] = []

    @property
    def is_superadmin(self) -> bool:
        """Check if user is a superadmin."""
        return self.id in settings.superadmin_ids


# Anonymous user returned when auth is disabled
ANONYMOUS_USER = CurrentUser(
    id="anonymous",
    email=None,
    name="Anonymous",
    username="anonymous",
    roles=["viewer"],
)

# Cache for JWKS (JSON Web Key Set) with TTL
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_time: float = 0.0
_jwks_lock = asyncio.Lock()


async def get_jwks(*, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch and cache the JWKS from Zitadel.

    The cache expires after 1 hour (controlled by _JWKS_CACHE_TTL) to handle
    key rotation while avoiding excessive network requests. Uses double-checked
    locking to prevent cache stampede from concurrent requests.

    Args:
        force_refresh: If True, bypass the cache TTL and fetch fresh keys.
    """
    global _jwks_cache, _jwks_cache_time

    now = time.monotonic()
    if not force_refresh and _jwks_cache is not None and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache

    async with _jwks_lock:
        # Re-check after acquiring lock — another coroutine may have refreshed
        now = time.monotonic()
        if (
            not force_refresh
            and _jwks_cache is not None
            and (now - _jwks_cache_time) < _JWKS_CACHE_TTL
        ):
            return _jwks_cache

        # Build headers - if using internal URL, set Host header to match external domain
        headers = {}
        if settings.zitadel_internal_url:
            from urllib.parse import urlparse

            parsed = urlparse(settings.zitadel_issuer)
            headers["Host"] = parsed.netloc

        async with httpx.AsyncClient() as client:
            base_url = settings.zitadel_jwks_base_url
            oidc_config_url = f"{base_url}/.well-known/openid-configuration"
            try:
                resp = await client.get(oidc_config_url, headers=headers)
                resp.raise_for_status()
                oidc_config = resp.json()

                jwks_uri = oidc_config["jwks_uri"]
                if settings.zitadel_internal_url:
                    jwks_uri = jwks_uri.replace(
                        settings.zitadel_issuer, settings.zitadel_internal_url
                    )
                resp = await client.get(jwks_uri, headers=headers)
                resp.raise_for_status()
                jwks_data: dict[str, Any] = resp.json()
                _jwks_cache = jwks_data
                _jwks_cache_time = time.monotonic()
                return jwks_data
            except httpx.HTTPError as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Failed to fetch JWKS: {e}",
                ) from e


def clear_jwks_cache() -> None:
    """Clear the JWKS cache (useful for testing or key rotation)."""
    global _jwks_cache, _jwks_cache_time
    _jwks_cache = None
    _jwks_cache_time = 0.0


async def validate_token(token: str) -> TokenPayload:
    """Validate a JWT token and return its payload.

    Extracts Zitadel project roles from the token claims and includes them
    in the returned TokenPayload.
    """
    try:
        # Get JWKS for token verification
        jwks = await get_jwks()

        # Decode token header to get key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find the matching key
        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

        if rsa_key is None:
            # Key rotation: refresh JWKS once and retry the kid lookup
            jwks = await get_jwks(force_refresh=True)
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = key
                    break

        if rsa_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find appropriate key",
            )

        # Verify and decode the token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=settings.zitadel_issuer,
            options={"verify_aud": False},  # Audience verified manually below (aud/azp)
        )

        # Verify audience: token must be intended for our client
        aud = payload.get("aud")
        azp = payload.get("azp")
        client_id = settings.zitadel_client_id

        aud_valid = False
        if isinstance(aud, list):
            aud_valid = client_id in aud
        elif isinstance(aud, str):
            aud_valid = aud == client_id

        if not aud_valid and azp != client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid audience",
            )

        # Extract roles from the Zitadel claim before constructing TokenPayload
        roles = _extract_roles(payload)

        return TokenPayload(**payload, roles=roles)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {e}",
        ) from e


async def fetch_userinfo(access_token: str) -> dict[str, Any] | None:
    """Fetch user info from Zitadel's userinfo endpoint."""
    base_url = settings.zitadel_internal_url or settings.zitadel_issuer

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    # If using internal URL, set Host header
    if settings.zitadel_internal_url:
        from urllib.parse import urlparse

        parsed = urlparse(settings.zitadel_issuer)
        headers["Host"] = parsed.netloc

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/oidc/v1/userinfo",
                headers=headers,
                timeout=10.0,
            )
            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result
    except httpx.HTTPError:
        pass

    return None


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> CurrentUser:
    """
    Get the current authenticated user from the JWT token.

    Raises 401 if not authenticated.
    """
    if settings.auth_mode == "disabled":
        return ANONYMOUS_USER
    # "optional" mode: still require auth for RequiredUser (401 if no credentials)
    # "required" mode: existing behavior (401 if no credentials)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_payload = await validate_token(credentials.credentials)

    # Try to get additional user info from userinfo endpoint
    name = token_payload.name
    email = token_payload.email
    username = token_payload.preferred_username
    roles = token_payload.roles

    if not name or not email or not roles:
        userinfo = await fetch_userinfo(credentials.credentials)
        if userinfo:
            name = name or userinfo.get("name") or userinfo.get("preferred_username")
            email = email or userinfo.get("email")
            username = username or userinfo.get("preferred_username")
            if not roles:
                roles = _extract_roles(userinfo)

    return CurrentUser(
        id=token_payload.sub,
        email=email,
        name=name,
        username=username,
        roles=roles,
    )


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> CurrentUser | None:
    """
    Get the current user if authenticated, otherwise return None.

    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
    if settings.auth_mode == "disabled":
        return ANONYMOUS_USER
    # "optional" mode: existing behavior — returns None if no credentials, real user if valid token
    # "required" mode: existing behavior
    if credentials is None:
        return None

    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


async def get_current_user_with_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> tuple[CurrentUser, str]:
    """
    Get the current authenticated user and their access token.

    Raises 401 if not authenticated.
    Returns tuple of (CurrentUser, access_token).
    """
    if settings.auth_mode == "disabled":
        return ANONYMOUS_USER, "anonymous"
    # "optional" and "required" modes: existing behavior (401 if no credentials)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_payload = await validate_token(credentials.credentials)

    # Try to get additional user info from userinfo endpoint
    name = token_payload.name
    email = token_payload.email
    username = token_payload.preferred_username
    roles = token_payload.roles

    if not name or not email or not roles:
        userinfo = await fetch_userinfo(credentials.credentials)
        if userinfo:
            name = name or userinfo.get("name") or userinfo.get("preferred_username")
            email = email or userinfo.get("email")
            username = username or userinfo.get("preferred_username")
            if not roles:
                roles = _extract_roles(userinfo)

    user = CurrentUser(
        id=token_payload.sub,
        email=email,
        name=name,
        username=username,
        roles=roles,
    )

    return user, credentials.credentials


# Type aliases for dependency injection
RequiredUser = Annotated[CurrentUser, Depends(get_current_user)]
OptionalUser = Annotated[CurrentUser | None, Depends(get_current_user_optional)]
RequiredUserWithToken = Annotated[tuple[CurrentUser, str], Depends(get_current_user_with_token)]


# Permission checking
class PermissionChecker:
    """Check if user has required permissions."""

    def __init__(self, required_roles: list[str] | None = None):
        self.required_roles = required_roles or []

    async def __call__(self, user: RequiredUser) -> CurrentUser:
        if self.required_roles:
            user_roles = set(user.roles)
            required = set(self.required_roles)
            if not required.intersection(user_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions",
                )
        return user


def require_roles(*roles: str) -> Any:
    """Dependency to require specific roles."""
    return Depends(PermissionChecker(list(roles)))
