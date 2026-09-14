"""Domain structures, kept independent from the database and user interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from math import isnan
from typing import Any


def _normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and isnan(value):
        return None
    normalized = str(value).strip().replace(" ", "")
    if normalized.lower() in {"", "nan", "none", "null"}:
        return None
    return normalized.upper() or None


class ProductType(str, Enum):
    BANK_ACCOUNT = "bank_account"
    INVESTMENT = "investment"
    STOCK_INDEX = "stock_index"
    FUND = "fund"
    CASH = "cash"
    PENSION = "pension"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    OTHER = "other"


@dataclass(frozen=True)
class Product:
    name: str
    product_type: ProductType
    currency: str = "EUR"
    institution: str | None = None
    labels: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    iban: str | None = None
    isin: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A product needs a name.")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("Currency must be a three-letter ISO code.")
        object.__setattr__(self, "iban", _normalize_identifier(self.iban))
        object.__setattr__(self, "isin", _normalize_identifier(self.isin))


@dataclass(frozen=True)
class Registry:
    product_id: int
    amount: Decimal
    recorded_on: date
    labels: tuple[str, ...] = ()
    note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def __post_init__(self) -> None:
        if self.product_id < 1:
            raise ValueError("Registry records must belong to a saved product.")
