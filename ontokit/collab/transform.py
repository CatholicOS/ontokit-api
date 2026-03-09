"""Operational Transformation for concurrent edits."""

from ontokit.collab.protocol import Operation, OperationType


def transform(op1: Operation, op2: Operation) -> tuple[Operation | None, Operation | None]:
    """
    Transform two concurrent operations so they can both be applied.

    Returns (op1', op2') where applying op1 then op2' = applying op2 then op1'

    This implements a simplified OT algorithm suitable for ontology operations.
    """
    # Same path: last-write-wins based on timestamp
    if op1.path == op2.path:
        if op1.timestamp > op2.timestamp:
            # op1 wins, op2 becomes no-op
            return op1, None
        else:
            # op2 wins, op1 becomes no-op
            return None, op2

    # Parent-child relationship: handle cascading deletes
    if _is_delete(op2) and op1.path.startswith(op2.path + "/"):
        # op2 deletes parent of op1's target, op1 becomes no-op
        return None, op2

    if _is_delete(op1) and op2.path.startswith(op1.path + "/"):
        # op1 deletes parent of op2's target, op2 becomes no-op
        return op1, None

    # Independent paths: both apply unchanged
    return op1, op2


def _is_delete(op: Operation) -> bool:
    """Check if an operation is a delete operation."""
    return op.type in (
        OperationType.DELETE_CLASS,
        OperationType.DELETE_PROPERTY,
        OperationType.DELETE_INDIVIDUAL,
        OperationType.REMOVE_AXIOM,
        OperationType.REMOVE_ANNOTATION,
        OperationType.REMOVE_IMPORT,
    )


def transform_against_history(op: Operation, history: list[Operation]) -> Operation | None:
    """
    Transform an operation against a list of already-applied operations.

    Returns the transformed operation, or None if it was nullified.
    """
    transformed: Operation | None = op

    for historical_op in history:
        if transformed is None:
            break

        # Only transform against operations with higher version
        if historical_op.version <= op.version:
            continue

        transformed, _ = transform(transformed, historical_op)

    return transformed
