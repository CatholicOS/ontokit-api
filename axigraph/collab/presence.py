"""User presence tracking for collaboration sessions."""

from datetime import datetime, timedelta

from axigraph.collab.protocol import User


class PresenceTracker:
    """Tracks user presence in collaboration rooms."""

    def __init__(self) -> None:
        # room_id -> {user_id -> User}
        self._rooms: dict[str, dict[str, User]] = {}
        # user_id -> last_seen timestamp
        self._last_seen: dict[str, datetime] = {}
        # Color palette for cursor colors
        self._colors = [
            "#FF6B6B",  # Red
            "#4ECDC4",  # Teal
            "#45B7D1",  # Blue
            "#96CEB4",  # Green
            "#FFEAA7",  # Yellow
            "#DDA0DD",  # Plum
            "#98D8C8",  # Mint
            "#F7DC6F",  # Gold
            "#BB8FCE",  # Purple
            "#85C1E9",  # Sky blue
        ]

    def join(self, room: str, user: User) -> list[User]:
        """Add user to room and return current user list."""
        if room not in self._rooms:
            self._rooms[room] = {}

        # Assign a color based on user count
        user_count = len(self._rooms[room])
        user.color = self._colors[user_count % len(self._colors)]

        self._rooms[room][user.user_id] = user
        self._last_seen[user.user_id] = datetime.utcnow()

        return list(self._rooms[room].values())

    def leave(self, room: str, user_id: str) -> list[User]:
        """Remove user from room and return updated user list."""
        if room in self._rooms and user_id in self._rooms[room]:
            del self._rooms[room][user_id]

            # Clean up empty rooms
            if not self._rooms[room]:
                del self._rooms[room]
                return []

        return list(self._rooms.get(room, {}).values())

    def update_cursor(self, room: str, user_id: str, path: str) -> None:
        """Update user's cursor position."""
        if room in self._rooms and user_id in self._rooms[room]:
            self._rooms[room][user_id].cursor_path = path
            self._last_seen[user_id] = datetime.utcnow()

    def get_users(self, room: str) -> list[User]:
        """Get all users in a room."""
        return list(self._rooms.get(room, {}).values())

    def heartbeat(self, user_id: str) -> None:
        """Update last seen timestamp for a user."""
        self._last_seen[user_id] = datetime.utcnow()

    def cleanup_stale(self, timeout_minutes: int = 5) -> list[tuple[str, str]]:
        """
        Remove users who haven't been seen recently.

        Returns list of (room, user_id) tuples for removed users.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        removed = []

        for room, users in list(self._rooms.items()):
            for user_id in list(users.keys()):
                if self._last_seen.get(user_id, datetime.min) < cutoff:
                    del users[user_id]
                    removed.append((room, user_id))

            # Clean up empty rooms
            if not users:
                del self._rooms[room]

        return removed

    def get_room_count(self) -> int:
        """Get number of active rooms."""
        return len(self._rooms)

    def get_user_count(self) -> int:
        """Get total number of connected users."""
        return sum(len(users) for users in self._rooms.values())
