from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from bankhuman.database import Database
from bankhuman.models import Product, ProductType, Registry


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.db")
        self.database.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_saves_product_and_historical_registries(self):
        product = self.database.add_product(Product(
            name="Main account", product_type=ProductType.BANK_ACCOUNT,
            labels=("daily",), metadata={"iban_last4": "1234"},
        ))
        self.database.add_registry(Registry(product.id, Decimal("100.50"), date(2026, 1, 1)))
        self.database.add_registry(Registry(product.id, Decimal("120.75"), date(2026, 2, 1), labels=("reviewed",)))

        products = self.database.list_products()
        current = self.database.latest_registries()

        self.assertEqual(products[0].metadata["iban_last4"], "1234")
        self.assertEqual(current[0][0].amount, Decimal("120.75"))
        self.assertEqual(current[0][0].labels, ("reviewed",))

    def test_latest_record_uses_date_not_insert_order(self):
        product = self.database.add_product(Product("ETF", ProductType.INVESTMENT))
        self.database.add_registry(Registry(product.id, Decimal("200"), date(2026, 2, 1)))
        self.database.add_registry(Registry(product.id, Decimal("100"), date(2026, 1, 1)))
        self.assertEqual(self.database.latest_registries()[0][0].amount, Decimal("200"))

    def test_delete_registry_removes_one_record(self):
        product = self.database.add_product(Product("Checking", ProductType.BANK_ACCOUNT))
        registry = self.database.add_registry(Registry(product.id, Decimal("150.00"), date(2026, 3, 1)))

        self.assertTrue(self.database.delete_registry(registry.id))
        self.assertEqual(self.database.list_registries(), [])

    def test_delete_product_removes_related_registries(self):
        product = self.database.add_product(Product("Broker", ProductType.INVESTMENT))
        registry = self.database.add_registry(Registry(product.id, Decimal("250.00"), date(2026, 4, 1)))

        self.assertTrue(self.database.delete_product(product.id))
        self.assertEqual(self.database.list_products(), [])
        self.assertEqual(self.database.list_registries(), [])
        self.assertFalse(self.database.delete_registry(registry.id))

    def test_find_product_by_iban_or_isin(self):
        product = self.database.add_product(Product(
            "Broker",
            ProductType.INVESTMENT,
            iban="ES9121000418450200051332",
            isin="US0378331005",
        ))

        self.assertEqual(self.database.find_product_by_identifier("ES9121000418450200051332"), product)
        self.assertEqual(self.database.find_product_by_identifier("US0378331005"), product)

    def test_import_excel_creates_missing_products_and_registries(self):
        file_path = Path(self.temp_dir.name) / "positions.xlsx"
        pd.DataFrame([
            {
                "name": "Cash account",
                "product_type": "bank_account",
                "currency": "EUR",
                "iban": "ES9121000418450200051332",
                "isin": "",
                "amount": "1250.00",
                "date": "2026-09-10",
            },
            {
                "name": "SP500",
                "product_type": "stock_index",
                "currency": "USD",
                "iban": "",
                "isin": "US78378X1072",
                "amount": "4300.50",
                "date": "2026-09-10",
            },
        ]).to_excel(file_path, index=False)

        created = self.database.import_excel(file_path)

        self.assertEqual(created, 2)
        self.assertEqual(len(self.database.list_products()), 2)
        self.assertEqual(len(self.database.list_registries()), 2)
        self.assertEqual(self.database.find_product_by_identifier("US78378X1072").name, "SP500")
