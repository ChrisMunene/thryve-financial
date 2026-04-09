"""
Auth schemas — what the application sees.

CurrentUser is the typed object every endpoint receives.
No raw dicts, no untyped token payloads.
"""

import uuid

from pydantic import BaseModel, Field


class CurrentUser(BaseModel):
    """Authenticated user context available in every request."""

    user_id: uuid.UUID
    email: str
    roles: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
