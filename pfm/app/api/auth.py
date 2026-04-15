"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Security, status

from app.auth.auth_context import AuthContext
from app.auth.bearer import get_bearer_token
from app.auth.principal import Principal
from app.auth.service import AuthService
from app.auth.types import AuthActionResult, AuthSession, AuthenticatedUser, PasswordSignUpResult
from app.core.idempotency import skip_idempotency
from app.core.rate_limit import RateLimitTier, rate_limit
from app.core.responses import Response, success_response
from app.dependencies import get_auth_service, require_auth, require_user
from app.schemas.auth import (
    EmailVerificationConfirmRequest,
    EmailVerificationRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordSignInRequest,
    PasswordSignUpRequest,
    RefreshSessionRequest,
)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(rate_limit(RateLimitTier.AUTH))],
)


@router.post(
    "/sign-up/password",
    status_code=status.HTTP_201_CREATED,
    response_model=Response[PasswordSignUpResult],
)
@skip_idempotency
async def sign_up_with_password(
    payload: PasswordSignUpRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[PasswordSignUpResult]:
    result = await auth_service.sign_up_with_password(
        email=payload.email,
        password=payload.password.get_secret_value(),
        display_name=payload.display_name,
    )
    return success_response(result)


@router.post(
    "/sign-in/password",
    response_model=Response[AuthSession],
)
@skip_idempotency
async def sign_in_with_password(
    payload: PasswordSignInRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthSession]:
    result = await auth_service.sign_in_with_password(
        email=payload.email,
        password=payload.password.get_secret_value(),
    )
    return success_response(result)


@router.post(
    "/refresh",
    response_model=Response[AuthSession],
)
@skip_idempotency
async def refresh_session(
    payload: RefreshSessionRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthSession]:
    result = await auth_service.refresh_session(refresh_token=payload.refresh_token)
    return success_response(result)


@router.post(
    "/password-reset/request",
    response_model=Response[AuthActionResult],
)
@skip_idempotency
async def request_password_reset(
    payload: PasswordResetRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthActionResult]:
    result = await auth_service.request_password_reset(email=payload.email)
    return success_response(result)


@router.post(
    "/password-reset/confirm",
    response_model=Response[AuthActionResult],
)
@skip_idempotency
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthActionResult]:
    result = await auth_service.confirm_password_reset(
        email=payload.email,
        token=payload.token,
        new_password=payload.new_password.get_secret_value(),
    )
    return success_response(result)


@router.post(
    "/email-verification/request",
    response_model=Response[AuthActionResult],
)
@skip_idempotency
async def request_email_verification(
    payload: EmailVerificationRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthActionResult]:
    result = await auth_service.request_email_verification(email=payload.email)
    return success_response(result)


@router.post(
    "/email-verification/confirm",
    response_model=Response[AuthActionResult],
)
@skip_idempotency
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthActionResult]:
    result = await auth_service.confirm_email_verification(
        email=payload.email,
        token=payload.token,
    )
    return success_response(result)


@router.post(
    "/logout",
    response_model=Response[AuthActionResult],
)
@skip_idempotency
async def logout(
    _principal: Principal = Security(require_auth),
    token: str = Security(get_bearer_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response[AuthActionResult]:
    _ = _principal
    result = await auth_service.logout(access_token=token)
    return success_response(result)


@router.get(
    "/me",
    response_model=Response[AuthenticatedUser],
)
async def me(
    auth_context: AuthContext = Depends(require_user),
) -> Response[AuthenticatedUser]:
    return success_response(auth_context.user)
