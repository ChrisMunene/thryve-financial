"""
Supabase auth delegate.

Verifies Supabase JWTs using the configured shared JWT secret.
JWKS-based verification is not implemented yet.
"""

import jwt

from app.auth.delegate import TokenPayload
from app.config import get_settings
from app.core.exceptions import AuthenticationRequiredError


class SupabaseAuthDelegate:
    """AuthDelegate implementation for Supabase Auth using HS256 shared secrets."""

    def __init__(self) -> None:
        settings = get_settings()
        self._jwt_secret = settings.auth.supabase_jwt_secret.get_secret_value()
        self._algorithms = ["HS256"]

    async def verify_token(self, token: str) -> TokenPayload:
        try:
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=self._algorithms,
                options={
                    # Supabase JWTs use "authenticated" as the aud claim but
                    # there is no server-side audience value configured yet.
                    # TODO: Set AUTH_SUPABASE_JWT_AUDIENCE in config and enable
                    # verify_aud once audience validation requirements are defined.
                    "verify_aud": False,
                },
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationRequiredError.token_expired()
        except jwt.InvalidTokenError as e:
            raise AuthenticationRequiredError.invalid_token(
                jwt_error_type=type(e).__name__
            )

        user_id = payload.get("sub")
        email = payload.get("email", "")
        role = payload.get("role", "user")
        user_metadata = payload.get("user_metadata", {})

        if not user_id:
            raise AuthenticationRequiredError.missing_subject_claim()

        return TokenPayload(
            user_id=user_id,
            email=email,
            roles=[role],
            metadata=user_metadata,
        )

    async def refresh_token(self, token: str) -> str:
        # Supabase handles refresh via its own client SDK on the Flutter side.
        # This is a server-side fallback if needed.
        raise AuthenticationRequiredError.unsupported_refresh_path()

    def validate_configuration(self) -> None:
        if not self._jwt_secret:
            raise RuntimeError("AUTH_SUPABASE_JWT_SECRET is required for auth readiness")
