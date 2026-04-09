"""
Mock auth delegate for tests.

Returns a configurable user for any token. No network calls.
Auto-wired in the test suite via DI overrides.
"""

import uuid

from app.auth.delegate import TokenPayload


class MockAuthDelegate:
    """Returns a configurable test user for any token."""

    def __init__(
        self,
        user_id: str | None = None,
        email: str = "test@example.com",
        roles: list[str] | None = None,
    ) -> None:
        self._user_id = user_id or str(uuid.uuid4())
        self._email = email
        self._roles = roles or ["user"]

    async def verify_token(self, token: str) -> TokenPayload:
        return TokenPayload(
            user_id=self._user_id,
            email=self._email,
            roles=self._roles,
        )

    async def refresh_token(self, token: str) -> str:
        return "mock-refreshed-token"
