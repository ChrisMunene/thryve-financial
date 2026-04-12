"""User remediation actions supported by first-party clients."""

from enum import StrEnum


class UserAction(StrEnum):
    RETRY = "retry"
    REAUTHENTICATE = "reauthenticate"
    REAUTHENTICATE_BANK = "reauthenticate_bank"
    CONTACT_SUPPORT = "contact_support"


__all__ = ["UserAction"]
