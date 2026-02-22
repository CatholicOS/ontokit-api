"""Tests for the Settings configuration module."""

import pytest

from ontokit.core.config import Settings


@pytest.fixture
def default_settings() -> Settings:
    """Create a Settings instance with defaults (ignoring .env file)."""
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
    )


class TestDefaultSettings:
    """Tests for default settings values."""

    def test_default_settings(self, default_settings: Settings) -> None:
        """Default settings have correct values."""
        assert default_settings.app_name == "OntoKit API"
        assert default_settings.app_env == "development"
        assert default_settings.debug is False
        assert default_settings.host == "0.0.0.0"
        assert default_settings.port == 8000
        assert default_settings.cors_origins == ["http://localhost:3000"]
        assert default_settings.superadmin_user_ids == ""
        assert default_settings.git_repos_base_path == "/data/repos"


class TestSuperadminIds:
    """Tests for the superadmin_ids property."""

    def test_superadmin_ids_empty(self) -> None:
        """Empty string returns empty set."""
        s = Settings(
            _env_file=None,
            superadmin_user_ids="",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.superadmin_ids == set()

    def test_superadmin_ids_single(self) -> None:
        """Single user ID returns a set with one element."""
        s = Settings(
            _env_file=None,
            superadmin_user_ids="user1",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.superadmin_ids == {"user1"}

    def test_superadmin_ids_multiple(self) -> None:
        """Comma-separated user IDs returns a set with multiple elements."""
        s = Settings(
            _env_file=None,
            superadmin_user_ids="user1,user2",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.superadmin_ids == {"user1", "user2"}

    def test_superadmin_ids_whitespace(self) -> None:
        """Whitespace around user IDs is stripped properly."""
        s = Settings(
            _env_file=None,
            superadmin_user_ids=" user1 , user2 ",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.superadmin_ids == {"user1", "user2"}

    def test_superadmin_ids_trailing_comma(self) -> None:
        """Trailing comma does not produce an empty-string entry."""
        s = Settings(
            _env_file=None,
            superadmin_user_ids="user1,user2,",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.superadmin_ids == {"user1", "user2"}


class TestEnvironmentProperties:
    """Tests for the is_development and is_production properties."""

    def test_is_development(self) -> None:
        """Development env returns True for is_development."""
        s = Settings(
            _env_file=None,
            app_env="development",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.is_development is True
        assert s.is_production is False

    def test_is_production(self) -> None:
        """Production env returns True for is_production."""
        s = Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.is_production is True
        assert s.is_development is False

    def test_is_staging(self) -> None:
        """Staging env returns False for both is_development and is_production."""
        s = Settings(
            _env_file=None,
            app_env="staging",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.is_development is False
        assert s.is_production is False


class TestZitadelJwksBaseUrl:
    """Tests for the zitadel_jwks_base_url property."""

    def test_zitadel_jwks_base_url_default(self) -> None:
        """Returns issuer when no internal URL is set."""
        s = Settings(
            _env_file=None,
            zitadel_issuer="https://auth.example.com",
            zitadel_internal_url=None,
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.zitadel_jwks_base_url == "https://auth.example.com"

    def test_zitadel_jwks_base_url_internal(self) -> None:
        """Returns internal URL when set, overriding the issuer."""
        s = Settings(
            _env_file=None,
            zitadel_issuer="https://auth.example.com",
            zitadel_internal_url="http://zitadel:8080",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.zitadel_jwks_base_url == "http://zitadel:8080"
