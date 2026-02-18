"""Authentication and authorization utilities."""

from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from axigraph.core.config import settings

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


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


# Cache for JWKS (JSON Web Key Set)
_jwks_cache: dict | None = None


async def get_jwks() -> dict:
    """Fetch and cache the JWKS from Zitadel."""
    global _jwks_cache

    if _jwks_cache is not None:
        return _jwks_cache

    # Build headers - if using internal URL, set Host header to match external domain
    # This is needed because Zitadel validates the Host header against its external domain
    headers = {}
    if settings.zitadel_internal_url:
        # Extract host from issuer URL (e.g., "localhost:8080" from "http://localhost:8080")
        from urllib.parse import urlparse

        parsed = urlparse(settings.zitadel_issuer)
        headers["Host"] = parsed.netloc

    async with httpx.AsyncClient() as client:
        # Fetch OpenID configuration
        # Use internal URL for Docker-to-Docker communication
        base_url = settings.zitadel_jwks_base_url
        oidc_config_url = f"{base_url}/.well-known/openid-configuration"
        try:
            resp = await client.get(oidc_config_url, headers=headers)
            resp.raise_for_status()
            oidc_config = resp.json()

            # Fetch JWKS - replace issuer URL with internal URL if needed
            jwks_uri = oidc_config["jwks_uri"]
            if settings.zitadel_internal_url:
                # Replace the external issuer URL with internal URL in jwks_uri
                jwks_uri = jwks_uri.replace(settings.zitadel_issuer, settings.zitadel_internal_url)
            resp = await client.get(jwks_uri, headers=headers)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            return _jwks_cache
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch JWKS: {e}",
            ) from e


def clear_jwks_cache() -> None:
    """Clear the JWKS cache (useful for testing or key rotation)."""
    global _jwks_cache
    _jwks_cache = None


async def validate_token(token: str) -> TokenPayload:
    """Validate a JWT token and return its payload."""
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
            options={"verify_aud": False},  # We'll verify audience manually if needed
        )

        return TokenPayload(**payload)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {e}",
        ) from e


async def fetch_userinfo(access_token: str) -> dict | None:
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
                return response.json()
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

    if not name or not email:
        userinfo = await fetch_userinfo(credentials.credentials)
        if userinfo:
            name = name or userinfo.get("name") or userinfo.get("preferred_username")
            email = email or userinfo.get("email")
            username = username or userinfo.get("preferred_username")

    return CurrentUser(
        id=token_payload.sub,
        email=email,
        name=name,
        username=username,
        roles=[],  # TODO: Extract roles from token claims
    )


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> CurrentUser | None:
    """
    Get the current user if authenticated, otherwise return None.

    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
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

    if not name or not email:
        userinfo = await fetch_userinfo(credentials.credentials)
        if userinfo:
            name = name or userinfo.get("name") or userinfo.get("preferred_username")
            email = email or userinfo.get("email")
            username = username or userinfo.get("preferred_username")

    user = CurrentUser(
        id=token_payload.sub,
        email=email,
        name=name,
        username=username,
        roles=[],
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


def require_roles(*roles: str):
    """Dependency to require specific roles."""
    return Depends(PermissionChecker(list(roles)))
