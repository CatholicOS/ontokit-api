"""User GitHub token model for storing encrypted PATs."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from axigraph.core.database import Base


class UserGitHubToken(Base):
    """Encrypted GitHub Personal Access Token stored per user."""

    __tablename__ = "user_github_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    github_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_scopes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<UserGitHubToken(user_id={self.user_id!r}, github_username={self.github_username!r})>"
        )
