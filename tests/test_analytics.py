from datetime import date
from decimal import Decimal
import unittest

from bankhuman.analytics import (
    apply_dashboard_filters,
    current_by_type,
    evolution_by_product,
    records_dataframe,
)
from bankhuman.models import Product, ProductType, Registry


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        account = Product("Checking", ProductType.BANK_ACCOUNT, owner="yo", id=1)
        fund = Product("Global fund", ProductType.FUND, currency="USD", owner="YO", id=2)
        casa = Product("Casa", ProductType.OTHER, owner="yo", id=3)
        other_owner = Product("Shared", ProductType.CASH, owner="partner", id=4)
        self.records = [
            (Registry(1, Decimal("100"), date(2026, 1, 1), id=1), account),
            (Registry(1, Decimal("150"), date(2026, 2, 1), id=2), account),
            (Registry(2, Decimal("200"), date(2026, 1, 1), id=3), fund),
            (Registry(3, Decimal("500"), date(2026, 2, 1), id=4), casa),
            (Registry(4, Decimal("900"), date(2026, 2, 1), id=5), other_owner),
        ]

    def test_dashboard_filters_match_notebook_defaults(self):
        filtered = apply_dashboard_filters(records_dataframe(self.records))
        self.assertEqual(set(filtered["product"]), {"Checking", "Global fund"})

    def test_current_totals_keep_currencies_separate(self):
        filtered = apply_dashboard_filters(records_dataframe([self.records[1], self.records[2]]))
        totals = current_by_type(filtered)
        self.assertEqual(
            {(row.currency, row.product_type, row.amount) for row in totals.itertuples()},
            {("EUR", "bank_account", 150.0), ("USD", "fund", 200.0)},
        )

    def test_evolution_uses_latest_value_at_each_snapshot(self):
        dataframe = apply_dashboard_filters(records_dataframe(self.records))
        evolution = evolution_by_product(dataframe)
        checking = evolution[
            (evolution["label"] == "Checking (EUR)")
            & (evolution["series"] == "Product")
        ]
        self.assertEqual(list(checking["amount"]), [100.0, 150.0])
        total = evolution[
            (evolution["label"] == "Total (EUR)")
            & (evolution["series"] == "Total")
        ]
        self.assertEqual(list(total["amount"]), [100.0, 150.0])

    def test_empty_evolution_is_safe(self):
        empty = records_dataframe([])
        self.assertTrue(evolution_by_product(empty).empty)


if __name__ == "__main__":
    unittest.main()
