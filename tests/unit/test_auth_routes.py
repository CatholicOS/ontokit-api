"""Tests for authentication routes (device flow and token refresh)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient


class TestDeviceCodeEndpoint:
    """Tests for POST /api/v1/auth/device/code."""

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_request_device_code_success(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        """Successful device code request returns expected fields."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "device_code": "dev-code-123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://auth.example.com/device",
            "verification_uri_complete": "https://auth.example.com/device?user_code=ABCD-1234",
            "expires_in": 600,
            "interval": 5,
        }

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/device/code", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["device_code"] == "dev-code-123"
        assert data["user_code"] == "ABCD-1234"
        assert data["verification_uri"] == "https://auth.example.com/device"
        assert data["expires_in"] == 600

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_request_device_code_with_custom_client_id(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        """Device code request with custom client_id passes it through."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "device_code": "dev-code-456",
            "user_code": "WXYZ-5678",
            "verification_uri": "https://auth.example.com/device",
            "expires_in": 300,
            "interval": 10,
        }

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post(
            "/api/v1/auth/device/code",
            json={"client_id": "custom-client", "scope": "openid profile"},
        )
        assert response.status_code == 200
        assert response.json()["device_code"] == "dev-code-456"

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_request_device_code_zitadel_error(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        """Zitadel HTTP error is forwarded as HTTPException."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable",
            request=MagicMock(),
            response=mock_response,
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/device/code", json={})
        assert response.status_code == 503
        assert "Failed to get device code" in response.json()["detail"]


class TestDeviceTokenEndpoint:
    """Tests for POST /api/v1/auth/device/token."""

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_poll_for_token_success(self, mock_client_cls: MagicMock, client: TestClient) -> None:
        """Successful token exchange returns access token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "eyJ.access.token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-tok",
            "id_token": "eyJ.id.token",
        }

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/device/token", json={"device_code": "dev-code-123"})
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "eyJ.access.token"
        assert data["token_type"] == "Bearer"
        assert data["refresh_token"] == "refresh-tok"

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_poll_for_token_authorization_pending(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        """Authorization pending returns 400 with specific detail."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "authorization_pending"}

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/device/token", json={"device_code": "dev-code-123"})
        assert response.status_code == 400
        assert response.json()["detail"] == "authorization_pending"

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_poll_for_token_expired(self, mock_client_cls: MagicMock, client: TestClient) -> None:
        """Expired device code returns 400 with expired_token detail."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "expired_token"}

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/device/token", json={"device_code": "dev-code-123"})
        assert response.status_code == 400
        assert response.json()["detail"] == "expired_token"


class TestTokenRefreshEndpoint:
    """Tests for POST /api/v1/auth/token/refresh."""

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_refresh_token_success(self, mock_client_cls: MagicMock, client: TestClient) -> None:
        """Successful token refresh returns new access token."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "access_token": "eyJ.new-access.token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-tok",
        }

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post(
            "/api/v1/auth/token/refresh", params={"refresh_token": "old-refresh-tok"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "eyJ.new-access.token"
        assert data["refresh_token"] == "new-refresh-tok"

    @patch("ontokit.api.routes.auth.httpx.AsyncClient")
    def test_refresh_token_zitadel_error(
        self, mock_client_cls: MagicMock, client: TestClient
    ) -> None:
        """Zitadel error during refresh is forwarded."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_ctx

        response = client.post("/api/v1/auth/token/refresh", params={"refresh_token": "bad-token"})
        assert response.status_code == 401
        assert "Token refresh failed" in response.json()["detail"]
