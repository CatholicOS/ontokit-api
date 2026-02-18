"""Authentication schemas."""

from pydantic import BaseModel


class DeviceCodeRequest(BaseModel):
    """Request for device authorization code."""

    client_id: str | None = None
    scope: str | None = None


class DeviceCodeResponse(BaseModel):
    """Response containing device code for user authentication."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None = None
    expires_in: int
    interval: int = 5


class TokenRequest(BaseModel):
    """Request to exchange device code for token."""

    device_code: str


class TokenResponse(BaseModel):
    """OAuth2 token response."""

    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str | None = None
    id_token: str | None = None
