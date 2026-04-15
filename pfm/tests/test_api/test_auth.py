"""API tests for the backend-owned auth endpoints."""

from __future__ import annotations

from app.auth.mock import MockAuthService
from app.dependencies import get_auth_service


async def test_sign_up_returns_session_when_email_verification_not_required(client):
    response = await client.post(
        "/api/v1/auth/sign-up/password",
        json={
            "email": "signup@example.com",
            "password": "super-secret-password",
            "display_name": "Signup User",
        },
    )

    assert response.status_code == 201
    assert response.json()["ok"] is True
    assert response.json()["data"]["email"] == "signup@example.com"
    assert response.json()["data"]["requires_email_verification"] is False
    assert response.json()["data"]["session"]["access_token"] == "mock-access-token"
    assert response.json()["data"]["user"]["display_name"] == "Signup User"


async def test_sign_up_can_return_pending_email_verification(app, client):
    app.dependency_overrides[get_auth_service] = lambda: MockAuthService(
        requires_email_verification=True
    )

    response = await client.post(
        "/api/v1/auth/sign-up/password",
        json={
            "email": "pending@example.com",
            "password": "super-secret-password",
            "display_name": "Pending User",
        },
    )

    assert response.status_code == 201
    assert response.json()["data"] == {
        "email": "pending@example.com",
        "requires_email_verification": True,
        "session": None,
        "user": None,
    }


async def test_sign_in_returns_session(client):
    response = await client.post(
        "/api/v1/auth/sign-in/password",
        json={
            "email": "signin@example.com",
            "password": "super-secret-password",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["access_token"] == "mock-access-token"
    assert response.json()["data"]["refresh_token"] == "mock-refresh-token"
    assert response.json()["data"]["user"]["email"] == "signin@example.com"


async def test_refresh_returns_session(client):
    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["access_token"] == "mock-access-token"
    assert response.json()["data"]["user"]["email"] == "test@example.com"


async def test_password_reset_request_returns_generic_message(client):
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "person@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["message"] == (
        "If an account exists for that email, reset instructions have been sent."
    )


async def test_password_reset_confirm_returns_success_message(client):
    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": "person@example.com",
            "token": "reset-token",
            "new_password": "new-super-secret-password",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "Your password has been updated."


async def test_email_verification_request_returns_generic_message(client):
    response = await client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": "person@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["message"] == (
        "If an account exists for that email, verification instructions have been sent."
    )


async def test_email_verification_confirm_returns_success_message(client):
    response = await client.post(
        "/api/v1/auth/email-verification/confirm",
        json={
            "email": "person@example.com",
            "token": "verification-token",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "Your email address has been verified."


async def test_logout_requires_authentication(client):
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_logout_returns_success_message_when_authenticated(client):
    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "You have been signed out."


async def test_me_returns_authenticated_user(client):
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == "test@example.com"
    assert response.json()["data"]["identities"][0]["provider"] == "mock"


async def test_me_requires_authentication(client):
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
