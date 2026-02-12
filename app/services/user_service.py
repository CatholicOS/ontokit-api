"""User service for fetching user information from Zitadel."""

from typing import TypedDict

import httpx

from app.core.config import settings


class UserInfo(TypedDict):
    """User information from Zitadel."""

    id: str
    name: str | None
    email: str | None


class UserService:
    """Service for fetching user information from Zitadel."""

    def __init__(self) -> None:
        self._cache: dict[str, UserInfo] = {}

    def _get_service_token(self) -> str | None:
        """
        Get the service account token (PAT) from settings.

        This token has management API access for user lookups.
        """
        return settings.zitadel_service_token or None

    async def get_user_info(self, user_id: str, access_token: str | None = None) -> UserInfo | None:
        """
        Get user information from Zitadel.

        Uses the Zitadel management API to fetch user details.
        Results are cached in memory for the lifetime of the service instance.

        Args:
            user_id: The Zitadel user ID
            access_token: Unused, kept for backward compatibility

        Returns:
            UserInfo dict with id, name, and email, or None if not found
        """
        # Check cache first
        if user_id in self._cache:
            return self._cache[user_id]

        # Get service token for management API access
        service_token = self._get_service_token()
        if not service_token:
            return None

        # Build the API URL
        base_url = settings.zitadel_internal_url or settings.zitadel_issuer
        url = f"{base_url}/management/v1/users/{user_id}"

        # Build headers
        headers = {
            "Authorization": f"Bearer {service_token}",
            "Content-Type": "application/json",
        }

        # If using internal URL, set Host header
        if settings.zitadel_internal_url:
            from urllib.parse import urlparse
            parsed = urlparse(settings.zitadel_issuer)
            headers["Host"] = parsed.netloc

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)

                if response.status_code == 200:
                    data = response.json()
                    user = data.get("user", {})
                    human = user.get("human", {})
                    profile = human.get("profile", {})
                    email_data = human.get("email", {})

                    # Build display name from profile
                    display_name = profile.get("displayName")
                    if not display_name:
                        first_name = profile.get("firstName", "")
                        last_name = profile.get("lastName", "")
                        display_name = f"{first_name} {last_name}".strip() or None

                    user_info: UserInfo = {
                        "id": user_id,
                        "name": display_name,
                        "email": email_data.get("email"),
                    }

                    # Cache the result
                    self._cache[user_id] = user_info
                    return user_info

                else:
                    return None

        except httpx.HTTPError:
            return None

    async def get_users_info(
        self, user_ids: list[str], access_token: str | None = None
    ) -> dict[str, UserInfo]:
        """
        Get information for multiple users.

        Args:
            user_ids: List of Zitadel user IDs
            access_token: Unused, kept for backward compatibility

        Returns:
            Dict mapping user_id to UserInfo for users that were found
        """
        result: dict[str, UserInfo] = {}

        for user_id in user_ids:
            user_info = await self.get_user_info(user_id)
            if user_info:
                result[user_id] = user_info

        return result

    def clear_cache(self) -> None:
        """Clear the user info cache."""
        self._cache.clear()


# Singleton instance for caching
_user_service: UserService | None = None


def get_user_service() -> UserService:
    """Get the user service singleton."""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
