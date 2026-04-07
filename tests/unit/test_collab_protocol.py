"""Tests for the WebSocket collaboration protocol models and enums."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ontokit.collab.protocol import (
    CollabMessage,
    CursorPayload,
    JoinPayload,
    MessageType,
    Operation,
    OperationPayload,
    OperationType,
    SyncRequestPayload,
    SyncResponsePayload,
    User,
    UserListPayload,
)


class TestMessageType:
    """Tests for MessageType enum values."""

    def test_connection_lifecycle_values(self) -> None:
        """Connection lifecycle message types have correct string values."""
        assert MessageType.AUTHENTICATE == "authenticate"  # type: ignore[comparison-overlap]
        assert MessageType.AUTHENTICATED == "authenticated"  # type: ignore[comparison-overlap]
        assert MessageType.ERROR == "error"  # type: ignore[comparison-overlap]

    def test_room_management_values(self) -> None:
        """Room management message types have correct string values."""
        assert MessageType.JOIN == "join"  # type: ignore[comparison-overlap]
        assert MessageType.LEAVE == "leave"  # type: ignore[comparison-overlap]
        assert MessageType.USER_LIST == "user_list"  # type: ignore[comparison-overlap]

    def test_presence_values(self) -> None:
        """Presence message types have correct string values."""
        assert MessageType.PRESENCE_UPDATE == "presence_update"  # type: ignore[comparison-overlap]
        assert MessageType.CURSOR_MOVE == "cursor_move"  # type: ignore[comparison-overlap]

    def test_operation_values(self) -> None:
        """Operation message types have correct string values."""
        assert MessageType.OPERATION == "operation"  # type: ignore[comparison-overlap]
        assert MessageType.OPERATION_ACK == "operation_ack"  # type: ignore[comparison-overlap]
        assert MessageType.OPERATION_REJECT == "operation_reject"  # type: ignore[comparison-overlap]

    def test_sync_values(self) -> None:
        """Sync message types have correct string values."""
        assert MessageType.SYNC_REQUEST == "sync_request"  # type: ignore[comparison-overlap]
        assert MessageType.SYNC_RESPONSE == "sync_response"  # type: ignore[comparison-overlap]

    def test_is_strenum(self) -> None:
        """MessageType values are strings."""
        assert isinstance(MessageType.JOIN, str)
        assert MessageType.JOIN == "join"  # type: ignore[comparison-overlap]


class TestOperationType:
    """Tests for OperationType enum values."""

    def test_class_operations(self) -> None:
        """Class operation types have correct string values."""
        assert OperationType.ADD_CLASS == "add_class"  # type: ignore[comparison-overlap]
        assert OperationType.UPDATE_CLASS == "update_class"  # type: ignore[comparison-overlap]
        assert OperationType.DELETE_CLASS == "delete_class"  # type: ignore[comparison-overlap]
        assert OperationType.MOVE_CLASS == "move_class"  # type: ignore[comparison-overlap]

    def test_property_operations(self) -> None:
        """Property operation types have correct string values."""
        assert OperationType.ADD_OBJECT_PROPERTY == "add_object_property"  # type: ignore[comparison-overlap]
        assert OperationType.ADD_DATA_PROPERTY == "add_data_property"  # type: ignore[comparison-overlap]
        assert OperationType.ADD_ANNOTATION_PROPERTY == "add_annotation_property"  # type: ignore[comparison-overlap]
        assert OperationType.UPDATE_PROPERTY == "update_property"  # type: ignore[comparison-overlap]
        assert OperationType.DELETE_PROPERTY == "delete_property"  # type: ignore[comparison-overlap]

    def test_individual_operations(self) -> None:
        """Individual operation types have correct string values."""
        assert OperationType.ADD_INDIVIDUAL == "add_individual"  # type: ignore[comparison-overlap]
        assert OperationType.UPDATE_INDIVIDUAL == "update_individual"  # type: ignore[comparison-overlap]
        assert OperationType.DELETE_INDIVIDUAL == "delete_individual"  # type: ignore[comparison-overlap]

    def test_axiom_operations(self) -> None:
        """Axiom operation types have correct string values."""
        assert OperationType.ADD_AXIOM == "add_axiom"  # type: ignore[comparison-overlap]
        assert OperationType.REMOVE_AXIOM == "remove_axiom"  # type: ignore[comparison-overlap]

    def test_annotation_operations(self) -> None:
        """Annotation operation types have correct string values."""
        assert OperationType.SET_ANNOTATION == "set_annotation"  # type: ignore[comparison-overlap]
        assert OperationType.REMOVE_ANNOTATION == "remove_annotation"  # type: ignore[comparison-overlap]

    def test_import_operations(self) -> None:
        """Import operation types have correct string values."""
        assert OperationType.ADD_IMPORT == "add_import"  # type: ignore[comparison-overlap]
        assert OperationType.REMOVE_IMPORT == "remove_import"  # type: ignore[comparison-overlap]


class TestOperation:
    """Tests for the Operation Pydantic model."""

    def test_valid_construction(self) -> None:
        """An Operation can be constructed with all required fields."""
        now = datetime.now(tz=UTC)
        op = Operation(
            id="abc-123",
            type=OperationType.ADD_CLASS,
            path="/classes/Person",
            timestamp=now,
            user_id="user1",
            version=1,
        )
        assert op.id == "abc-123"
        assert op.type == OperationType.ADD_CLASS
        assert op.path == "/classes/Person"
        assert op.timestamp == now
        assert op.user_id == "user1"
        assert op.version == 1

    def test_optional_defaults(self) -> None:
        """Optional fields default to None."""
        op = Operation(
            id="abc-123",
            type=OperationType.ADD_CLASS,
            path="/classes/Person",
            timestamp=datetime.now(tz=UTC),
            user_id="user1",
            version=1,
        )
        assert op.value is None
        assert op.previous_value is None

    def test_value_fields(self) -> None:
        """Value and previous_value can hold arbitrary data."""
        op = Operation(
            id="abc-123",
            type=OperationType.UPDATE_CLASS,
            path="/classes/Person",
            value={"label": "Human"},
            previous_value={"label": "Person"},
            timestamp=datetime.now(tz=UTC),
            user_id="user1",
            version=2,
        )
        assert op.value == {"label": "Human"}
        assert op.previous_value == {"label": "Person"}

    def test_missing_required_field_raises(self) -> None:
        """Missing a required field raises a ValidationError."""
        with pytest.raises(ValidationError):
            Operation(  # type: ignore[call-arg]
                type=OperationType.ADD_CLASS,
                path="/classes/Person",
                timestamp=datetime.now(tz=UTC),
                user_id="user1",
                version=1,
                # missing 'id'
            )

    def test_invalid_operation_type_raises(self) -> None:
        """An invalid operation type raises a ValidationError."""
        with pytest.raises(ValidationError):
            Operation(
                id="abc-123",
                type="not_a_real_type",  # type: ignore[arg-type]
                path="/classes/Person",
                timestamp=datetime.now(tz=UTC),
                user_id="user1",
                version=1,
            )


class TestUser:
    """Tests for the User Pydantic model."""

    def test_required_fields(self) -> None:
        """User requires user_id, display_name, client_type, client_version."""
        user = User(
            user_id="user1",
            display_name="Alice",
            client_type="web",
            client_version="1.0.0",
        )
        assert user.user_id == "user1"
        assert user.display_name == "Alice"
        assert user.client_type == "web"
        assert user.client_version == "1.0.0"

    def test_optional_fields_default_none(self) -> None:
        """Optional fields cursor_path and color default to None."""
        user = User(
            user_id="user1",
            display_name="Alice",
            client_type="web",
            client_version="1.0.0",
        )
        assert user.cursor_path is None
        assert user.color is None

    def test_optional_fields_can_be_set(self) -> None:
        """Optional fields can be provided at construction."""
        user = User(
            user_id="user1",
            display_name="Alice",
            client_type="web",
            client_version="1.0.0",
            cursor_path="/classes/Person",
            color="#FF6B6B",
        )
        assert user.cursor_path == "/classes/Person"
        assert user.color == "#FF6B6B"

    def test_missing_required_field_raises(self) -> None:
        """Missing required fields raise a ValidationError."""
        with pytest.raises(ValidationError):
            User(  # type: ignore[call-arg]
                user_id="user1",
                display_name="Alice",
                # missing client_type and client_version
            )


class TestCollabMessage:
    """Tests for the CollabMessage wire-format model."""

    def test_minimal_construction(self) -> None:
        """A CollabMessage can be created with just a type."""
        msg = CollabMessage(type=MessageType.AUTHENTICATE)
        assert msg.type == MessageType.AUTHENTICATE
        assert msg.payload == {}
        assert msg.room is None
        assert msg.seq is None

    def test_full_construction(self) -> None:
        """A CollabMessage can be created with all fields."""
        msg = CollabMessage(
            type=MessageType.OPERATION,
            payload={"operation_id": "op-1"},
            room="project-123",
            seq=42,
        )
        assert msg.type == MessageType.OPERATION
        assert msg.payload == {"operation_id": "op-1"}
        assert msg.room == "project-123"
        assert msg.seq == 42

    def test_serialization_round_trip(self) -> None:
        """A CollabMessage can be serialized to dict and back."""
        original = CollabMessage(
            type=MessageType.JOIN,
            payload={"user_id": "user1"},
            room="room-abc",
            seq=1,
        )
        data = original.model_dump()
        restored = CollabMessage.model_validate(data)

        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.room == original.room
        assert restored.seq == original.seq

    def test_json_round_trip(self) -> None:
        """A CollabMessage can be serialized to JSON and back."""
        original = CollabMessage(
            type=MessageType.CURSOR_MOVE,
            payload={"path": "/classes/Person"},
            room="room-1",
        )
        json_str = original.model_dump_json()
        restored = CollabMessage.model_validate_json(json_str)

        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.room == original.room


class TestJoinPayload:
    """Tests for JoinPayload model."""

    def test_valid_construction(self) -> None:
        """JoinPayload can be constructed with all required fields."""
        payload = JoinPayload(
            user_id="user1",
            display_name="Alice",
            client_type="web",
            client_version="2.0.0",
        )
        assert payload.user_id == "user1"
        assert payload.display_name == "Alice"
        assert payload.client_type == "web"
        assert payload.client_version == "2.0.0"

    def test_missing_field_raises(self) -> None:
        """Missing required fields raise a ValidationError."""
        with pytest.raises(ValidationError):
            JoinPayload(user_id="user1")  # type: ignore[call-arg]


class TestOperationPayload:
    """Tests for OperationPayload model."""

    def test_valid_construction(self) -> None:
        """OperationPayload wraps an Operation."""
        op = Operation(
            id="op-1",
            type=OperationType.ADD_CLASS,
            path="/classes/Person",
            timestamp=datetime.now(tz=UTC),
            user_id="user1",
            version=1,
        )
        payload = OperationPayload(operation=op)
        assert payload.operation.id == "op-1"

    def test_missing_operation_raises(self) -> None:
        """Missing operation field raises a ValidationError."""
        with pytest.raises(ValidationError):
            OperationPayload()  # type: ignore[call-arg]


class TestCursorPayload:
    """Tests for CursorPayload model."""

    def test_valid_construction(self) -> None:
        """CursorPayload can be constructed with required fields."""
        payload = CursorPayload(user_id="user1", path="/classes/Person")
        assert payload.user_id == "user1"
        assert payload.path == "/classes/Person"
        assert payload.selection is None

    def test_with_selection(self) -> None:
        """CursorPayload can include a selection range."""
        payload = CursorPayload(
            user_id="user1",
            path="/classes/Person",
            selection={"start": 10, "end": 25},
        )
        assert payload.selection == {"start": 10, "end": 25}


class TestUserListPayload:
    """Tests for UserListPayload model."""

    def test_valid_construction(self) -> None:
        """UserListPayload holds a list of User objects."""
        user = User(
            user_id="user1",
            display_name="Alice",
            client_type="web",
            client_version="1.0.0",
        )
        payload = UserListPayload(users=[user])
        assert len(payload.users) == 1
        assert payload.users[0].user_id == "user1"

    def test_empty_user_list(self) -> None:
        """UserListPayload can hold an empty list."""
        payload = UserListPayload(users=[])
        assert payload.users == []


class TestSyncPayloads:
    """Tests for SyncRequestPayload and SyncResponsePayload."""

    def test_sync_request(self) -> None:
        """SyncRequestPayload holds the last known version."""
        payload = SyncRequestPayload(last_version=42)
        assert payload.last_version == 42

    def test_sync_response(self) -> None:
        """SyncResponsePayload holds operations and current version."""
        op = Operation(
            id="op-1",
            type=OperationType.ADD_CLASS,
            path="/classes/Person",
            timestamp=datetime.now(tz=UTC),
            user_id="user1",
            version=1,
        )
        payload = SyncResponsePayload(operations=[op], current_version=5)
        assert len(payload.operations) == 1
        assert payload.current_version == 5

    def test_sync_response_empty_operations(self) -> None:
        """SyncResponsePayload can hold an empty operations list."""
        payload = SyncResponsePayload(operations=[], current_version=0)
        assert payload.operations == []
        assert payload.current_version == 0
