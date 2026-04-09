"""
Auth delegate protocol.

The delegate handles vendor-specific token verification.
The AuthService wraps it with logging, analytics, and error handling.
Swap vendors by swapping the delegate — app code never changes.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """Decoded token data returned by the delegate."""

    user_id: str
    email: str
    roles: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


@runtime_checkable
class AuthDelegate(Protocol):
    """Protocol for authentication delegates.

    Implementations:
    - SupabaseAuthDelegate (production)
    - MockAuthDelegate (tests)
    """

    async def verify_token(self, token: str) -> TokenPayload:
        """Verify a JWT token and return the payload.

        Raises AuthenticationError if the token is invalid, expired, or malformed.
        """
        ...

    async def refresh_token(self, token: str) -> str:
        """Refresh an expired token and return the new token string.

        Raises AuthenticationError if the refresh token is invalid.
        """
        ...
