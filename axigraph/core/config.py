"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Axigraph API"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = Field(default="change-me-in-production")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://axigraph:axigraph@localhost:5432/axigraph"
    )

    # Redis
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    # MinIO / S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123"
    minio_bucket: str = "axigraph"
    minio_secure: bool = False

    # Git Repository Storage
    git_repos_base_path: str = "/data/repos"

    # Zitadel Authentication
    zitadel_issuer: str = "http://localhost:8080"
    zitadel_internal_url: str | None = None  # Internal URL for JWKS fetch (defaults to issuer)
    zitadel_client_id: str = ""
    zitadel_client_secret: str = ""
    zitadel_service_token: str = ""  # PAT for service account (user lookups)

    @property
    def zitadel_jwks_base_url(self) -> str:
        """URL to use for fetching JWKS (internal URL in Docker, issuer otherwise)."""
        return self.zitadel_internal_url or self.zitadel_issuer

    # CORS
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

    # GitHub Integration
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_token_encryption_key: str = ""

    # Frontend / Sitemap Revalidation
    frontend_url: str = ""  # e.g. http://localhost:3000
    revalidation_secret: str = ""  # shared secret for sitemap revalidation

    # Superadmin - comma-separated list of user IDs with full system access
    superadmin_user_ids: str = ""

    @property
    def superadmin_ids(self) -> set[str]:
        """Get set of superadmin user IDs."""
        if not self.superadmin_user_ids:
            return set()
        return {uid.strip() for uid in self.superadmin_user_ids.split(",") if uid.strip()}

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
