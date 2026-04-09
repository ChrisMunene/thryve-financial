"""
Test factories for creating model instances with sensible defaults.

Usage:
    user = create_user(email="custom@example.com")
    txn = create_transaction(amount=Decimal("19.99"))
"""

import uuid

from app.auth.schemas import CurrentUser


def create_current_user(**overrides) -> CurrentUser:
    """Create a CurrentUser for testing."""
    defaults = {
        "user_id": uuid.uuid4(),
        "email": "test@example.com",
        "roles": ["user"],
        "metadata": {},
    }
    defaults.update(overrides)
    return CurrentUser(**defaults)


# Additional factories (create_user, create_transaction) will be added
# when SQLAlchemy models are defined in the categorization-engine change.
