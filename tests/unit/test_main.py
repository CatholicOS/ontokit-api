"""Tests for the main FastAPI application (ontokit/main.py)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from ontokit.core.config import settings
from ontokit.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ontokit.main import app, lifespan, unhandled_exception_handler


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


class TestUnhandledExceptionHandler:
    """Tests for the catch-all Exception handler (issue #98 follow-up).

    Without this handler, an exception escaping every other handler
    propagates to Starlette's outer ServerErrorMiddleware and the response
    goes out without CORS headers, so the browser blocks it before the
    frontend can read the status — masking the underlying bug behind an
    opaque "CORS error".
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env", ["production", "staging"])
    async def test_returns_json_500_in_non_development(
        self, monkeypatch: pytest.MonkeyPatch, env: str
    ) -> None:
        """In production and staging, the handler returns the project's
        standard error envelope at 500. Staging behaves like production so the
        response shape matches what the frontend will see live."""
        monkeypatch.setattr(settings, "app_env", env)

        response = await unhandled_exception_handler(Mock(), RuntimeError("kaboom"))

        assert response.status_code == 500
        # JSONResponse.body is always bytes at runtime; the assert narrows the
        # Starlette stub's bytes | memoryview[int] union for json.loads.
        assert isinstance(response.body, bytes)
        body = json.loads(response.body)
        assert body["error"]["code"] == "internal_server_error"
        assert body["error"]["message"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_reraises_in_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In development the handler re-raises so Starlette's debug page
        still surfaces the traceback for the developer."""
        monkeypatch.setattr(settings, "app_env", "development")

        with pytest.raises(RuntimeError, match="kaboom"):
            await unhandled_exception_handler(Mock(), RuntimeError("kaboom"))


class TestLifespan:
    """Tests for the application lifespan (startup + shutdown).

    These exercise the timeout / fail-fast paths added by PR #138 so that an
    unreachable database fails startup quickly and an unreachable Redis or
    MinIO degrades gracefully without blocking startup.
    """

    @pytest.fixture
    def patched_lifespan(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """Patch every external dependency the lifespan touches.

        Returns the mocks so individual tests can override behavior (e.g. raise
        TimeoutError) and assert on calls.
        """
        # Reset module-level redis_pool so leftover state from a previous test
        # doesn't affect shutdown branches.
        import ontokit.main as main_module

        monkeypatch.setattr(main_module, "redis_pool", None)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        connect_cm = AsyncMock()
        connect_cm.__aenter__.return_value = mock_conn
        connect_cm.__aexit__.return_value = None

        mock_engine = Mock()
        mock_engine.connect = Mock(return_value=connect_cm)
        mock_engine.dispose = AsyncMock()
        monkeypatch.setattr(main_module, "engine", mock_engine)

        redis_pool_mock = AsyncMock()
        redis_pool_mock.ping = AsyncMock()
        redis_pool_mock.close = AsyncMock()
        from_url = Mock(return_value=redis_pool_mock)
        # Patch via string path so mypy strict mode doesn't object to
        # `main_module.aioredis` (the alias isn't explicitly re-exported).
        monkeypatch.setattr("ontokit.main.aioredis.from_url", from_url)

        storage_instance = Mock()
        storage_instance.ensure_bucket_exists = AsyncMock()
        storage_cls = Mock(return_value=storage_instance)
        monkeypatch.setattr(main_module, "StorageService", storage_cls)

        close_arq = AsyncMock()
        monkeypatch.setattr("ontokit.api.utils.redis.close_arq_pool", close_arq)

        return {
            "engine": mock_engine,
            "conn": mock_conn,
            "redis_pool": redis_pool_mock,
            "redis_from_url": from_url,
            "storage": storage_instance,
            "close_arq": close_arq,
        }

    @pytest.mark.asyncio
    async def test_happy_path_runs_startup_and_shutdown(
        self, patched_lifespan: dict[str, Any]
    ) -> None:
        """When every backend is healthy, startup verifies all of them and
        shutdown disposes the engine and closes the Redis + ARQ pools."""
        async with lifespan(Mock()):
            patched_lifespan["conn"].execute.assert_awaited_once()
            patched_lifespan["redis_pool"].ping.assert_awaited_once()
            patched_lifespan["storage"].ensure_bucket_exists.assert_awaited_once()

        patched_lifespan["redis_pool"].close.assert_awaited_once()
        patched_lifespan["close_arq"].assert_awaited_once()
        patched_lifespan["engine"].dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_database_timeout_aborts_startup(self, patched_lifespan: dict[str, Any]) -> None:
        """A stuck DB connect must abort startup — we re-raise TimeoutError so
        the container exits and is restarted by the orchestrator."""
        patched_lifespan["conn"].execute.side_effect = asyncio.TimeoutError

        with pytest.raises(asyncio.TimeoutError):
            async with lifespan(Mock()):
                pytest.fail("lifespan should not have yielded after DB timeout")

    @pytest.mark.asyncio
    async def test_database_failure_aborts_startup(self, patched_lifespan: dict[str, Any]) -> None:
        """A non-timeout DB error (auth failure, bad config) also aborts."""
        patched_lifespan["conn"].execute.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            async with lifespan(Mock()):
                pytest.fail("lifespan should not have yielded after DB failure")

    @pytest.mark.asyncio
    async def test_redis_failure_continues_startup(self, patched_lifespan: dict[str, Any]) -> None:
        """Redis is optional — its failure must not block startup, and the
        module-level redis_pool must be left as None so feature code can
        detect the degraded state."""
        import ontokit.main as main_module

        patched_lifespan["redis_pool"].ping.side_effect = RuntimeError("redis down")

        async with lifespan(Mock()):
            assert main_module.redis_pool is None

    @pytest.mark.asyncio
    async def test_minio_timeout_continues_startup(self, patched_lifespan: dict[str, Any]) -> None:
        """MinIO is optional — a timeout must be swallowed so the API still
        comes up serving non-storage endpoints."""
        patched_lifespan["storage"].ensure_bucket_exists.side_effect = asyncio.TimeoutError

        async with lifespan(Mock()):
            patched_lifespan["storage"].ensure_bucket_exists.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_minio_failure_continues_startup(self, patched_lifespan: dict[str, Any]) -> None:
        """Same for non-timeout MinIO errors (auth, missing bucket, etc.)."""
        patched_lifespan["storage"].ensure_bucket_exists.side_effect = RuntimeError("nope")

        async with lifespan(Mock()):
            patched_lifespan["storage"].ensure_bucket_exists.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_swallows_cleanup_errors(self, patched_lifespan: dict[str, Any]) -> None:
        """Shutdown must complete even if individual cleanup steps raise —
        otherwise a flaky Redis can mask other shutdown work."""
        patched_lifespan["redis_pool"].close.side_effect = RuntimeError("close failed")
        patched_lifespan["close_arq"].side_effect = RuntimeError("arq close failed")
        patched_lifespan["engine"].dispose.side_effect = RuntimeError("dispose failed")

        # No exception should escape the lifespan exit.
        async with lifespan(Mock()):
            pass

        patched_lifespan["redis_pool"].close.assert_awaited_once()
        patched_lifespan["close_arq"].assert_awaited_once()
        patched_lifespan["engine"].dispose.assert_awaited_once()
