"""Role enum.

Values match the seed rows in database/script.sql ("Administrator", "Seller",
"Buyer") so teammate code that does ``role.name.lower() == "seller"`` keeps
working.
"""

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "Administrator"
    SELLER = "Seller"
    BUYER = "Buyer"
