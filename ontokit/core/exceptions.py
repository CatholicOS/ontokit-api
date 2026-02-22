"""Custom exception types and global exception handlers for OntoKit API."""

from typing import Any


class OntoKitError(Exception):
    """Base exception for all OntoKit domain errors."""

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(OntoKitError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str = "Resource", *, detail: Any = None) -> None:
        super().__init__(f"{resource} not found", detail=detail)
        self.resource = resource


class ValidationError(OntoKitError):
    """Raised when input validation fails at the domain level."""


class ConflictError(OntoKitError):
    """Raised when an operation conflicts with existing state."""


class ForbiddenError(OntoKitError):
    """Raised when the user lacks permission for the operation."""
