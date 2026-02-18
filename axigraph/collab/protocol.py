"""WebSocket collaboration protocol definitions."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """Types of collaboration messages."""

    # Connection lifecycle
    AUTHENTICATE = "authenticate"
    AUTHENTICATED = "authenticated"
    ERROR = "error"

    # Room management
    JOIN = "join"
    LEAVE = "leave"
    USER_LIST = "user_list"

    # Presence
    PRESENCE_UPDATE = "presence_update"
    CURSOR_MOVE = "cursor_move"

    # Operations
    OPERATION = "operation"
    OPERATION_ACK = "operation_ack"
    OPERATION_REJECT = "operation_reject"

    # Sync
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"


class OperationType(StrEnum):
    """Types of ontology operations."""

    # Class operations
    ADD_CLASS = "add_class"
    UPDATE_CLASS = "update_class"
    DELETE_CLASS = "delete_class"
    MOVE_CLASS = "move_class"

    # Property operations
    ADD_OBJECT_PROPERTY = "add_object_property"
    ADD_DATA_PROPERTY = "add_data_property"
    ADD_ANNOTATION_PROPERTY = "add_annotation_property"
    UPDATE_PROPERTY = "update_property"
    DELETE_PROPERTY = "delete_property"

    # Individual operations
    ADD_INDIVIDUAL = "add_individual"
    UPDATE_INDIVIDUAL = "update_individual"
    DELETE_INDIVIDUAL = "delete_individual"

    # Axiom operations
    ADD_AXIOM = "add_axiom"
    REMOVE_AXIOM = "remove_axiom"

    # Annotation operations
    SET_ANNOTATION = "set_annotation"
    REMOVE_ANNOTATION = "remove_annotation"

    # Import operations
    ADD_IMPORT = "add_import"
    REMOVE_IMPORT = "remove_import"


class Operation(BaseModel):
    """A single atomic change to the ontology."""

    id: str = Field(..., description="Unique operation ID (UUID)")
    type: OperationType
    path: str = Field(..., description="JSON path to element, e.g., /classes/Person")
    value: Any | None = None
    previous_value: Any | None = None
    timestamp: datetime
    user_id: str
    version: int = Field(..., description="Client's last known version")


class User(BaseModel):
    """A user in a collaboration session."""

    user_id: str
    display_name: str
    client_type: str  # web, java-desktop, dotnet-desktop, etc.
    client_version: str
    cursor_path: str | None = None
    color: str | None = None  # Assigned color for cursor


class CollabMessage(BaseModel):
    """Wire format for all WebSocket messages."""

    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    room: str | None = None
    seq: int | None = None


# Message payload schemas


class JoinPayload(BaseModel):
    """Payload for JOIN message."""

    user_id: str
    display_name: str
    client_type: str
    client_version: str


class UserListPayload(BaseModel):
    """Payload for USER_LIST message."""

    users: list[User]


class OperationPayload(BaseModel):
    """Payload for OPERATION message."""

    operation: Operation


class OperationAckPayload(BaseModel):
    """Payload for OPERATION_ACK message."""

    operation_id: str
    version: int
    server_time: datetime


class CursorPayload(BaseModel):
    """Payload for CURSOR_MOVE message."""

    user_id: str
    path: str
    selection: dict[str, int] | None = None  # {start, end} for text selection


class SyncRequestPayload(BaseModel):
    """Payload for SYNC_REQUEST message."""

    last_version: int


class SyncResponsePayload(BaseModel):
    """Payload for SYNC_RESPONSE message."""

    operations: list[Operation]
    current_version: int
