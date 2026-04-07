"""Tests for custom exception classes (ontokit/core/exceptions.py)."""

from __future__ import annotations

from ontokit.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    OntoKitError,
    ValidationError,
)


class TestOntoKitError:
    """Tests for the base OntoKitError."""

    def test_message_and_detail(self) -> None:
        """OntoKitError stores message and optional detail."""
        err = OntoKitError("something went wrong", detail={"key": "value"})
        assert err.message == "something went wrong"
        assert err.detail == {"key": "value"}
        assert str(err) == "something went wrong"

    def test_default_detail_is_none(self) -> None:
        """detail defaults to None when not provided."""
        err = OntoKitError("error")
        assert err.detail is None


class TestNotFoundError:
    """Tests for NotFoundError."""

    def test_default_resource(self) -> None:
        """Default resource name is 'Resource'."""
        err = NotFoundError()
        assert err.message == "Resource not found"
        assert err.resource == "Resource"

    def test_custom_resource(self) -> None:
        """Custom resource name is included in the message."""
        err = NotFoundError("Project", detail={"id": "123"})
        assert err.message == "Project not found"
        assert err.resource == "Project"
        assert err.detail == {"id": "123"}

    def test_is_ontokit_error(self) -> None:
        """NotFoundError is a subclass of OntoKitError."""
        assert issubclass(NotFoundError, OntoKitError)


class TestValidationAndConflictAndForbidden:
    """Tests for ValidationError, ConflictError, and ForbiddenError."""

    def test_validation_error(self) -> None:
        """ValidationError stores message and detail."""
        err = ValidationError("Invalid name", detail=["too short"])
        assert err.message == "Invalid name"
        assert err.detail == ["too short"]
        assert isinstance(err, OntoKitError)

    def test_conflict_error(self) -> None:
        """ConflictError stores message and detail."""
        err = ConflictError("Already exists")
        assert err.message == "Already exists"
        assert isinstance(err, OntoKitError)

    def test_forbidden_error(self) -> None:
        """ForbiddenError stores message and detail."""
        err = ForbiddenError("Not allowed", detail="admin only")
        assert err.message == "Not allowed"
        assert err.detail == "admin only"
        assert isinstance(err, OntoKitError)
