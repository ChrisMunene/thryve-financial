"""
Test factories for creating model instances with sensible defaults.

Usage:
    user = create_user(email="custom@example.com")
    txn = create_transaction(amount=Decimal("19.99"))
"""

import uuid

from app.auth.principal import Principal


def create_principal(**overrides) -> Principal:
    """Create a Principal for testing."""
    defaults = {
        "subject_id": str(uuid.uuid4()),
        "user_id": uuid.uuid4(),
        "email": "test@example.com",
        "roles": ["user"],
        "metadata": {},
    }
    defaults.update(overrides)
    return Principal(**defaults)


# Additional factories (create_user, create_transaction) will be added
# when SQLAlchemy models are defined in the categorization-engine change.
