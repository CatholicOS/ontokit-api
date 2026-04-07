"""Tests for the main FastAPI application (ontokit/main.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ontokit.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ontokit.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app, raise_server_exceptions=False)


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_returns_api_info(self, client: TestClient) -> None:
        """Root endpoint returns API name, version, docs URL, and openapi URL."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "OntoKit API"
        assert "version" in data
        assert data["docs"] == "/docs"
        assert data["openapi"] == "/openapi.json"


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_returns_healthy(self, client: TestClient) -> None:
        """Health endpoint returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestNotFoundErrorHandler:
    """Tests for the NotFoundError exception handler."""

    def test_returns_404_with_error_body(self, client: TestClient) -> None:
        """NotFoundError produces a 404 response with structured error body."""

        @app.get("/test-not-found")
        async def _raise_not_found() -> None:
            raise NotFoundError("Project")

        response = client.get("/test-not-found")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert "Project not found" in body["error"]["message"]


class TestValidationErrorHandler:
    """Tests for the ValidationError exception handler."""

    def test_returns_422_with_error_body(self, client: TestClient) -> None:
        """ValidationError produces a 422 response with structured error body."""

        @app.get("/test-validation")
        async def _raise_validation() -> None:
            raise ValidationError("Invalid input", detail={"field": "name"})

        response = client.get("/test-validation")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["message"] == "Invalid input"
        assert body["error"]["detail"] == {"field": "name"}


class TestConflictErrorHandler:
    """Tests for the ConflictError exception handler."""

    def test_returns_409_with_error_body(self, client: TestClient) -> None:
        """ConflictError produces a 409 response with structured error body."""

        @app.get("/test-conflict")
        async def _raise_conflict() -> None:
            raise ConflictError("Resource already exists")

        response = client.get("/test-conflict")
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "conflict"
        assert body["error"]["message"] == "Resource already exists"


class TestForbiddenErrorHandler:
    """Tests for the ForbiddenError exception handler."""

    def test_returns_403_with_error_body(self, client: TestClient) -> None:
        """ForbiddenError produces a 403 response with structured error body."""

        @app.get("/test-forbidden")
        async def _raise_forbidden() -> None:
            raise ForbiddenError("Access denied")

        response = client.get("/test-forbidden")
        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "forbidden"
        assert body["error"]["message"] == "Access denied"


class TestMiddlewareRegistered:
    """Tests that middleware is registered on the app."""

    def test_request_id_header_present(self, client: TestClient) -> None:
        """The RequestIDMiddleware adds an X-Request-ID header to responses."""
        response = client.get("/health")
        assert "x-request-id" in response.headers

    def test_security_headers_present(self, client: TestClient) -> None:
        """The SecurityHeadersMiddleware adds security headers to responses."""
        response = client.get("/health")
        # SecurityHeadersMiddleware should add common security headers
        assert "x-content-type-options" in response.headers
