"""Tests for the PresenceTracker collaboration module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from ontokit.collab.presence import PresenceTracker
from ontokit.collab.protocol import User


def _make_user(user_id: str = "user1", display_name: str = "Alice") -> User:
    """Create a User instance for testing."""
    return User(
        user_id=user_id,
        display_name=display_name,
        client_type="web",
        client_version="1.0.0",
    )


class TestJoin:
    """Tests for PresenceTracker.join()."""

    def test_join_adds_user_to_room(self) -> None:
        """Joining a room adds the user and returns the user list."""
        tracker = PresenceTracker()
        user = _make_user()
        users = tracker.join("room1", user)

        assert len(users) == 1
        assert users[0].user_id == "user1"

    def test_join_assigns_cursor_color(self) -> None:
        """Joining assigns a color from the palette."""
        tracker = PresenceTracker()
        user = _make_user()
        users = tracker.join("room1", user)

        assert users[0].color == "#FF6B6B"

    def test_join_assigns_different_colors_to_different_users(self) -> None:
        """Each user in a room gets a different color."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        users = tracker.join("room1", _make_user("user2", "Bob"))

        colors = {u.color for u in users}
        assert len(colors) == 2
        assert "#FF6B6B" in colors
        assert "#4ECDC4" in colors

    def test_join_creates_room_if_not_exists(self) -> None:
        """Joining a new room creates it automatically."""
        tracker = PresenceTracker()
        assert tracker.get_room_count() == 0

        tracker.join("room1", _make_user())
        assert tracker.get_room_count() == 1

    def test_join_same_room_twice_overwrites_user(self) -> None:
        """Joining the same room twice with the same user_id overwrites the entry."""
        tracker = PresenceTracker()
        user1 = _make_user("user1", "Alice")
        user2 = _make_user("user1", "Alice Updated")

        tracker.join("room1", user1)
        users = tracker.join("room1", user2)

        assert len(users) == 1
        assert users[0].display_name == "Alice Updated"

    def test_join_same_room_twice_reassigns_color(self) -> None:
        """Re-joining assigns color based on current user count (position 1, not 0)."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        # user1 is already in the room, so count is 1 before re-assignment
        users = tracker.join("room1", _make_user("user1", "Alice"))

        # count is 1 (user1 already present), so color index is 1
        assert users[0].color == "#4ECDC4"

    def test_join_color_wraps_around_palette(self) -> None:
        """Colors wrap around when more users than colors exist."""
        tracker = PresenceTracker()
        for i in range(11):
            tracker.join("room1", _make_user(f"user{i}", f"User {i}"))

        users = tracker.get_users("room1")
        # The 11th user (index 10) should wrap to color index 0
        user_10 = next(u for u in users if u.user_id == "user10")
        assert user_10.color == "#FF6B6B"

    def test_join_updates_last_seen(self) -> None:
        """Joining a room sets the last_seen timestamp."""
        tracker = PresenceTracker()
        user = _make_user()
        tracker.join("room1", user)

        assert "user1" in tracker._last_seen

    def test_join_multiple_rooms(self) -> None:
        """A user can join multiple rooms."""
        tracker = PresenceTracker()
        user1 = _make_user("user1", "Alice")
        user2 = _make_user("user1", "Alice")

        tracker.join("room1", user1)
        tracker.join("room2", user2)

        assert tracker.get_room_count() == 2
        assert len(tracker.get_users("room1")) == 1
        assert len(tracker.get_users("room2")) == 1


class TestLeave:
    """Tests for PresenceTracker.leave()."""

    def test_leave_removes_user_from_room(self) -> None:
        """Leaving removes the user from the room."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room1", _make_user("user2", "Bob"))

        users = tracker.leave("room1", "user1")
        assert len(users) == 1
        assert users[0].user_id == "user2"

    def test_leave_cleans_up_empty_room(self) -> None:
        """Leaving the last user in a room removes the room entirely."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user())

        users = tracker.leave("room1", "user1")
        assert users == []
        assert tracker.get_room_count() == 0

    def test_leave_nonexistent_room(self) -> None:
        """Leaving a room that does not exist returns an empty list."""
        tracker = PresenceTracker()
        users = tracker.leave("nonexistent", "user1")
        assert users == []

    def test_leave_nonexistent_user(self) -> None:
        """Leaving with a user_id not in the room returns the current user list."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))

        users = tracker.leave("room1", "ghost")
        assert len(users) == 1
        assert users[0].user_id == "user1"

    def test_leave_does_not_affect_other_rooms(self) -> None:
        """Leaving one room does not affect the user's presence in another room."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room2", _make_user("user1", "Alice"))

        tracker.leave("room1", "user1")
        assert tracker.get_room_count() == 1
        assert len(tracker.get_users("room2")) == 1


class TestUpdateCursor:
    """Tests for PresenceTracker.update_cursor()."""

    def test_update_cursor_sets_path(self) -> None:
        """Updating cursor sets the cursor_path on the user."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user())

        tracker.update_cursor("room1", "user1", "/classes/Person")
        users = tracker.get_users("room1")
        assert users[0].cursor_path == "/classes/Person"

    def test_update_cursor_updates_last_seen(self) -> None:
        """Updating cursor refreshes the last_seen timestamp."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user())
        old_time = tracker._last_seen["user1"]

        with patch("ontokit.collab.presence.datetime") as mock_dt:
            mock_dt.now.return_value = old_time + timedelta(seconds=10)
            tracker.update_cursor("room1", "user1", "/classes/Animal")

        assert tracker._last_seen["user1"] > old_time

    def test_update_cursor_nonexistent_room(self) -> None:
        """Updating cursor for a nonexistent room is a no-op."""
        tracker = PresenceTracker()
        tracker.update_cursor("nonexistent", "user1", "/classes/Person")
        # Should not raise

    def test_update_cursor_nonexistent_user(self) -> None:
        """Updating cursor for a nonexistent user in a room is a no-op."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.update_cursor("room1", "ghost", "/classes/Person")

        users = tracker.get_users("room1")
        assert users[0].cursor_path is None


class TestGetUsers:
    """Tests for PresenceTracker.get_users()."""

    def test_get_users_returns_all_users_in_room(self) -> None:
        """Returns all users currently in the room."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room1", _make_user("user2", "Bob"))

        users = tracker.get_users("room1")
        assert len(users) == 2

    def test_get_users_empty_room(self) -> None:
        """Returns empty list for a nonexistent room."""
        tracker = PresenceTracker()
        assert tracker.get_users("nonexistent") == []

    def test_get_users_returns_list_copy(self) -> None:
        """Returns a new list, not the internal data structure."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user())

        users1 = tracker.get_users("room1")
        users2 = tracker.get_users("room1")
        assert users1 is not users2


class TestHeartbeat:
    """Tests for PresenceTracker.heartbeat()."""

    def test_heartbeat_updates_last_seen(self) -> None:
        """Heartbeat updates the last_seen timestamp."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user())
        old_time = tracker._last_seen["user1"]

        with patch("ontokit.collab.presence.datetime") as mock_dt:
            mock_dt.now.return_value = old_time + timedelta(seconds=30)
            tracker.heartbeat("user1")

        assert tracker._last_seen["user1"] > old_time

    def test_heartbeat_unknown_user(self) -> None:
        """Heartbeat for an unknown user still records a timestamp."""
        tracker = PresenceTracker()
        tracker.heartbeat("ghost")
        assert "ghost" in tracker._last_seen


class TestCleanupStale:
    """Tests for PresenceTracker.cleanup_stale()."""

    def test_cleanup_removes_stale_users(self) -> None:
        """Users past the timeout are removed."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))

        # Backdate the last_seen timestamp
        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=10)

        removed = tracker.cleanup_stale(timeout_minutes=5)
        assert len(removed) == 1
        assert removed[0] == ("room1", "user1")
        assert tracker.get_room_count() == 0

    def test_cleanup_keeps_active_users(self) -> None:
        """Users within the timeout are not removed."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))

        removed = tracker.cleanup_stale(timeout_minutes=5)
        assert removed == []
        assert tracker.get_user_count() == 1

    def test_cleanup_mixed_stale_and_active(self) -> None:
        """Only stale users are removed; active users remain."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room1", _make_user("user2", "Bob"))

        # Make user1 stale, keep user2 active
        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=10)

        removed = tracker.cleanup_stale(timeout_minutes=5)
        assert len(removed) == 1
        assert removed[0] == ("room1", "user1")
        assert tracker.get_user_count() == 1

    def test_cleanup_removes_empty_rooms(self) -> None:
        """Rooms are removed when all users are cleaned up."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=10)

        tracker.cleanup_stale(timeout_minutes=5)
        assert tracker.get_room_count() == 0

    def test_cleanup_across_multiple_rooms(self) -> None:
        """Cleanup works across multiple rooms."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room2", _make_user("user2", "Bob"))

        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=10)
        tracker._last_seen["user2"] = datetime.now(tz=UTC) - timedelta(minutes=10)

        removed = tracker.cleanup_stale(timeout_minutes=5)
        assert len(removed) == 2
        assert tracker.get_room_count() == 0

    def test_cleanup_default_timeout(self) -> None:
        """Default timeout is 5 minutes."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=4)

        removed = tracker.cleanup_stale()
        assert removed == []

        tracker._last_seen["user1"] = datetime.now(tz=UTC) - timedelta(minutes=6)
        removed = tracker.cleanup_stale()
        assert len(removed) == 1


class TestRoomAndUserCounts:
    """Tests for get_room_count() and get_user_count()."""

    def test_initial_counts_are_zero(self) -> None:
        """A fresh tracker has zero rooms and zero users."""
        tracker = PresenceTracker()
        assert tracker.get_room_count() == 0
        assert tracker.get_user_count() == 0

    def test_counts_after_joins(self) -> None:
        """Counts reflect joined users and rooms."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room1", _make_user("user2", "Bob"))
        tracker.join("room2", _make_user("user3", "Charlie"))

        assert tracker.get_room_count() == 2
        assert tracker.get_user_count() == 3

    def test_counts_after_leave(self) -> None:
        """Counts decrease when users leave."""
        tracker = PresenceTracker()
        tracker.join("room1", _make_user("user1", "Alice"))
        tracker.join("room1", _make_user("user2", "Bob"))

        tracker.leave("room1", "user1")
        assert tracker.get_user_count() == 1

        tracker.leave("room1", "user2")
        assert tracker.get_user_count() == 0
        assert tracker.get_room_count() == 0
