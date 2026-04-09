"""
Plaid client — extends BaseClient.

Stubbed for now. Implemented fully in the categorization-engine change.
"""

from app.clients.base import BaseClient
from app.config import get_settings


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

    # Plaid API methods will be added in the categorization-engine change
