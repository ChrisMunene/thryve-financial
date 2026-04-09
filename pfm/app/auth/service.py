"""
Auth service — what the application sees.

Wraps the delegate with cross-cutting concerns:
logging, error handling, user context setting.
Analytics tracking will be wired in once the analytics service exists.
"""

import uuid

import structlog

from app.auth.delegate import AuthDelegate, TokenPayload
from app.auth.schemas import CurrentUser
from app.core.context import set_current_user_id
from app.core.exceptions import AuthenticationError

logger = structlog.get_logger()


class AuthService:
    """Application-facing auth service.

    The delegate handles vendor-specific token verification.
    This service handles logging, context, and error wrapping.
    """

    def __init__(self, delegate: AuthDelegate) -> None:
        self._delegate = delegate

    async def authenticate(self, token: str) -> CurrentUser:
        """Verify a token and return the authenticated user.

        Sets the user ID in the request context for logging.
        """
        try:
            payload: TokenPayload = await self._delegate.verify_token(token)
        except AuthenticationError:
            logger.warning("authentication.failed", reason="delegate_rejected")
            raise
        except Exception as e:
            logger.error("authentication.error", error=str(e))
            raise AuthenticationError("Authentication failed") from e

        # Set user context for logging
        set_current_user_id(payload.user_id)

        try:
            user_uuid = uuid.UUID(payload.user_id)
        except (ValueError, AttributeError):
            logger.warning("authentication.failed", reason="malformed_user_id")
            raise AuthenticationError("Invalid user ID in token")

        user = CurrentUser(
            user_id=user_uuid,
            email=payload.email,
            roles=payload.roles,
            metadata=payload.metadata,
        )

        logger.info(
            "user.authenticated",
            user_id=str(user.user_id),
            email=user.email,
        )

        # TODO: analytics.track("user.authenticated", ...) once analytics service exists

        return user

    def validate_configuration(self) -> None:
        """Validate that the delegate is configured for local readiness checks."""
        validator = getattr(self._delegate, "validate_configuration", None)
        if callable(validator):
            validator()
