"""Authentication endpoints including OAuth2 Device Flow."""

import httpx
from fastapi import APIRouter, HTTPException

from axigraph.core.config import settings
from axigraph.schemas.auth import DeviceCodeRequest, DeviceCodeResponse, TokenRequest, TokenResponse

router = APIRouter()


@router.post("/device/code", response_model=DeviceCodeResponse)
async def request_device_code(request: DeviceCodeRequest) -> DeviceCodeResponse:
    """
    Request a device code for OAuth2 Device Authorization Grant.

    Used by desktop applications to initiate authentication.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.zitadel_issuer}/oauth/v2/device_authorization",
                data={
                    "client_id": request.client_id or settings.zitadel_client_id,
                    "scope": request.scope or "openid profile email offline_access",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return DeviceCodeResponse(
                device_code=data["device_code"],
                user_code=data["user_code"],
                verification_uri=data["verification_uri"],
                verification_uri_complete=data.get("verification_uri_complete"),
                expires_in=data["expires_in"],
                interval=data.get("interval", 5),
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail="Failed to get device code"
            ) from e


@router.post("/device/token", response_model=TokenResponse)
async def poll_for_token(request: TokenRequest) -> TokenResponse:
    """
    Poll for token using device code.

    Desktop applications poll this endpoint until the user completes authentication.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.zitadel_issuer}/oauth/v2/token",
                data={
                    "client_id": settings.zitadel_client_id,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": request.device_code,
                },
            )

            if resp.status_code == 400:
                data = resp.json()
                error = data.get("error", "unknown_error")
                if error == "authorization_pending":
                    raise HTTPException(status_code=400, detail="authorization_pending")
                elif error == "slow_down":
                    raise HTTPException(status_code=400, detail="slow_down")
                elif error == "expired_token":
                    raise HTTPException(status_code=400, detail="expired_token")
                else:
                    raise HTTPException(status_code=400, detail=error)

            resp.raise_for_status()
            data = resp.json()
            return TokenResponse(
                access_token=data["access_token"],
                token_type=data["token_type"],
                expires_in=data["expires_in"],
                refresh_token=data.get("refresh_token"),
                id_token=data.get("id_token"),
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail="Token request failed"
            ) from e


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_token(refresh_token: str) -> TokenResponse:
    """Refresh an access token using a refresh token."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{settings.zitadel_issuer}/oauth/v2/token",
                data={
                    "client_id": settings.zitadel_client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return TokenResponse(
                access_token=data["access_token"],
                token_type=data["token_type"],
                expires_in=data["expires_in"],
                refresh_token=data.get("refresh_token"),
                id_token=data.get("id_token"),
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail="Token refresh failed"
            ) from e
