"""Tests for the Operational Transformation module."""

from datetime import UTC, datetime, timedelta

from ontokit.collab.protocol import Operation, OperationType
from ontokit.collab.transform import _is_delete, transform, transform_against_history


def _make_op(
    *,
    op_type: OperationType = OperationType.UPDATE_CLASS,
    path: str = "/classes/Person",
    timestamp: datetime | None = None,
    user_id: str = "user1",
    version: int = 1,
    op_id: str = "op-1",
) -> Operation:
    """Create an Operation instance for testing."""
    return Operation(
        id=op_id,
        type=op_type,
        path=path,
        timestamp=timestamp or datetime.now(tz=UTC),
        user_id=user_id,
        version=version,
    )


class TestTransformSamePath:
    """Tests for transform() when both operations target the same path."""

    def test_later_timestamp_wins(self) -> None:
        """The operation with the later timestamp wins (last-write-wins)."""
        now = datetime.now(tz=UTC)
        op1 = _make_op(path="/classes/Person", timestamp=now + timedelta(seconds=1), op_id="op-1")
        op2 = _make_op(path="/classes/Person", timestamp=now, op_id="op-2")

        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is None

    def test_earlier_timestamp_loses(self) -> None:
        """The operation with the earlier timestamp becomes a no-op."""
        now = datetime.now(tz=UTC)
        op1 = _make_op(path="/classes/Person", timestamp=now, op_id="op-1")
        op2 = _make_op(path="/classes/Person", timestamp=now + timedelta(seconds=1), op_id="op-2")

        result1, result2 = transform(op1, op2)
        assert result1 is None
        assert result2 is op2

    def test_equal_timestamps_op2_wins(self) -> None:
        """With equal timestamps, op2 wins (else branch)."""
        now = datetime.now(tz=UTC)
        op1 = _make_op(path="/classes/Person", timestamp=now, op_id="op-1")
        op2 = _make_op(path="/classes/Person", timestamp=now, op_id="op-2")

        result1, result2 = transform(op1, op2)
        assert result1 is None
        assert result2 is op2


class TestTransformParentChild:
    """Tests for transform() with parent-child path relationships."""

    def test_delete_parent_nullifies_child_op(self) -> None:
        """Deleting a parent path nullifies an operation on a child path."""
        op1 = _make_op(path="/classes/Person/name", op_id="op-child")
        op2 = _make_op(
            path="/classes/Person",
            op_type=OperationType.DELETE_CLASS,
            op_id="op-parent-delete",
        )

        result1, result2 = transform(op1, op2)
        assert result1 is None
        assert result2 is op2

    def test_delete_child_does_not_nullify_parent(self) -> None:
        """Deleting a child path does not affect the parent operation."""
        op1 = _make_op(path="/classes/Person", op_id="op-parent")
        op2 = _make_op(
            path="/classes/Person/name",
            op_type=OperationType.DELETE_PROPERTY,
            op_id="op-child-delete",
        )

        # Independent: different paths and no parent-child with delete
        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is op2

    def test_op1_deletes_parent_of_op2(self) -> None:
        """When op1 deletes the parent of op2's target, op2 becomes no-op."""
        op1 = _make_op(
            path="/classes/Animal",
            op_type=OperationType.DELETE_CLASS,
            op_id="op-delete",
        )
        op2 = _make_op(path="/classes/Animal/legs", op_id="op-child")

        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is None

    def test_path_prefix_must_be_exact_parent(self) -> None:
        """A path that is a prefix but not a parent (no /) does not trigger cascade."""
        op1 = _make_op(path="/classes/PersonName", op_id="op-1")
        op2 = _make_op(
            path="/classes/Person",
            op_type=OperationType.DELETE_CLASS,
            op_id="op-delete",
        )

        # "/classes/PersonName" does not start with "/classes/Person/"
        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is op2

    def test_non_delete_parent_does_not_nullify_child(self) -> None:
        """A non-delete operation on a parent path does not nullify a child."""
        op1 = _make_op(path="/classes/Person/name", op_id="op-child")
        op2 = _make_op(
            path="/classes/Person",
            op_type=OperationType.UPDATE_CLASS,
            op_id="op-parent-update",
        )

        # Different paths, no delete cascade
        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is op2


class TestTransformIndependentPaths:
    """Tests for transform() with independent paths."""

    def test_independent_paths_both_survive(self) -> None:
        """Operations on independent paths are both preserved."""
        op1 = _make_op(path="/classes/Person", op_id="op-1")
        op2 = _make_op(path="/classes/Animal", op_id="op-2")

        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is op2

    def test_completely_different_branches(self) -> None:
        """Operations in entirely different subtrees both survive."""
        op1 = _make_op(path="/classes/Person", op_id="op-1")
        op2 = _make_op(path="/properties/hasAge", op_id="op-2")

        result1, result2 = transform(op1, op2)
        assert result1 is op1
        assert result2 is op2


class TestIsDelete:
    """Tests for the _is_delete() helper function."""

    def test_delete_class_is_delete(self) -> None:
        """DELETE_CLASS is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.DELETE_CLASS)
        assert _is_delete(op) is True

    def test_delete_property_is_delete(self) -> None:
        """DELETE_PROPERTY is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.DELETE_PROPERTY)
        assert _is_delete(op) is True

    def test_delete_individual_is_delete(self) -> None:
        """DELETE_INDIVIDUAL is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.DELETE_INDIVIDUAL)
        assert _is_delete(op) is True

    def test_remove_axiom_is_delete(self) -> None:
        """REMOVE_AXIOM is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.REMOVE_AXIOM)
        assert _is_delete(op) is True

    def test_remove_annotation_is_delete(self) -> None:
        """REMOVE_ANNOTATION is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.REMOVE_ANNOTATION)
        assert _is_delete(op) is True

    def test_remove_import_is_delete(self) -> None:
        """REMOVE_IMPORT is recognized as a delete operation."""
        op = _make_op(op_type=OperationType.REMOVE_IMPORT)
        assert _is_delete(op) is True

    def test_add_class_is_not_delete(self) -> None:
        """ADD_CLASS is not a delete operation."""
        op = _make_op(op_type=OperationType.ADD_CLASS)
        assert _is_delete(op) is False

    def test_update_class_is_not_delete(self) -> None:
        """UPDATE_CLASS is not a delete operation."""
        op = _make_op(op_type=OperationType.UPDATE_CLASS)
        assert _is_delete(op) is False

    def test_set_annotation_is_not_delete(self) -> None:
        """SET_ANNOTATION is not a delete operation."""
        op = _make_op(op_type=OperationType.SET_ANNOTATION)
        assert _is_delete(op) is False

    def test_add_import_is_not_delete(self) -> None:
        """ADD_IMPORT is not a delete operation."""
        op = _make_op(op_type=OperationType.ADD_IMPORT)
        assert _is_delete(op) is False


class TestTransformAgainstHistory:
    """Tests for transform_against_history()."""

    def test_empty_history(self) -> None:
        """With no history, the operation is returned unchanged."""
        op = _make_op(version=1)
        result = transform_against_history(op, [])
        assert result is op

    def test_skips_lower_or_equal_version(self) -> None:
        """Historical operations with version <= op.version are skipped."""
        op = _make_op(path="/classes/Person", version=5, op_id="op-1")
        history = [
            _make_op(path="/classes/Person", version=3, op_id="hist-1"),
            _make_op(path="/classes/Person", version=5, op_id="hist-2"),
        ]

        result = transform_against_history(op, history)
        assert result is op

    def test_transforms_against_higher_version(self) -> None:
        """Operations with higher versions cause transformation."""
        now = datetime.now(tz=UTC)
        op = _make_op(
            path="/classes/Person",
            version=1,
            timestamp=now,
            op_id="op-1",
        )
        history = [
            _make_op(
                path="/classes/Person",
                version=2,
                timestamp=now + timedelta(seconds=1),
                op_id="hist-1",
            ),
        ]

        result = transform_against_history(op, history)
        # Same path, history op has later timestamp, so op is nullified
        assert result is None

    def test_null_propagation_stops_early(self) -> None:
        """Once nullified, the operation stays None through remaining history."""
        now = datetime.now(tz=UTC)
        op = _make_op(
            path="/classes/Person",
            version=1,
            timestamp=now,
            op_id="op-1",
        )
        history = [
            _make_op(
                path="/classes/Person",
                version=2,
                timestamp=now + timedelta(seconds=1),
                op_id="hist-1",
            ),
            _make_op(
                path="/classes/Person",
                version=3,
                timestamp=now + timedelta(seconds=2),
                op_id="hist-2",
            ),
        ]

        result = transform_against_history(op, history)
        assert result is None

    def test_chain_of_independent_transforms(self) -> None:
        """Independent operations in history leave the operation unchanged."""
        op = _make_op(path="/classes/Person", version=1, op_id="op-1")
        history = [
            _make_op(path="/classes/Animal", version=2, op_id="hist-1"),
            _make_op(path="/classes/Vehicle", version=3, op_id="hist-2"),
        ]

        result = transform_against_history(op, history)
        assert result is op

    def test_delete_parent_in_history_nullifies(self) -> None:
        """A delete of a parent path in history nullifies the child operation."""
        op = _make_op(path="/classes/Person/name", version=1, op_id="op-1")
        history = [
            _make_op(
                path="/classes/Person",
                op_type=OperationType.DELETE_CLASS,
                version=2,
                op_id="hist-delete",
            ),
        ]

        result = transform_against_history(op, history)
        assert result is None
