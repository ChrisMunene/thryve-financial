"""
Plaid client — extends BaseClient.

Stubbed for now. Implemented fully in the categorization-engine change.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.clients.base import BaseClient
from app.config import get_settings
from app.core.exceptions import DependencyUnavailableError
from app.core.responses import ProblemUpstream


class PlaidTransactionsSyncResult(BaseModel):
    """Minimal typed view of the Plaid transactions sync response."""

    added: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class PlaidClient(BaseClient):
    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=f"https://{settings.plaid.env}.plaid.com",
            service_name="plaid",
            timeout=30.0,
            max_retries=3,
        )
        self._client_id = settings.plaid.client_id
        self._secret = settings.plaid.secret.get_secret_value()

    async def sync_transactions(
        self,
        *,
        access_token: str,
        cursor: str | None = None,
        count: int = 100,
    ) -> PlaidTransactionsSyncResult:
        """Fetch a page of transactions using Plaid's sync endpoint."""

        response = await self.post(
            "/transactions/sync",
            json={
                "client_id": self._client_id,
                "secret": self._secret,
                "access_token": access_token,
                "cursor": cursor,
                "count": count,
            },
        )

        payload = response.json()
        if not isinstance(payload, dict):
            raise DependencyUnavailableError.for_service(
                "plaid",
                detail="Plaid returned an invalid transactions sync payload.",
                upstream=ProblemUpstream(provider="plaid"),
            )

        return PlaidTransactionsSyncResult(
            added=payload.get("added", []) if isinstance(payload.get("added"), list) else [],
            next_cursor=payload.get("next_cursor")
            if isinstance(payload.get("next_cursor"), str)
            else None,
            has_more=bool(payload.get("has_more", False)),
        )


_instance: PlaidClient | None = None


def get_plaid_client() -> PlaidClient:
    """Return a module-level singleton Plaid client."""

    global _instance
    if _instance is None:
        _instance = PlaidClient()
    return _instance


async def close_client() -> None:
    """Close the shared Plaid client during application shutdown."""

    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
