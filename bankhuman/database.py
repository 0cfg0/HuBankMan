"""SQLite persistence for personal-finance records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .models import Product, ProductType, Registry


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    institution TEXT,
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    iban TEXT,
                    isin TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS registries (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    amount TEXT NOT NULL,
                    recorded_on TEXT NOT NULL,
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS registries_product_date
                    ON registries(product_id, recorded_on DESC, id DESC);
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
            for column_name in ("iban", "isin"):
                if column_name not in columns:
                    db.execute(f"ALTER TABLE products ADD COLUMN {column_name} TEXT")

    def add_product(self, product: Product) -> Product:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO products
                   (name, product_type, currency, institution, labels_json, metadata_json, iban, isin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (product.name.strip(), product.product_type.value, product.currency.upper(),
                 product.institution, _dump(product.labels), _dump(product.metadata),
                 product.iban, product.isin),
            )
            return replace(product, id=cursor.lastrowid)

    def find_product_by_identifier(self, identifier: str | None) -> Product | None:
        normalized = _normalize_identifier(identifier)
        if not normalized:
            return None
        with self.connect() as db:
            row = db.execute(
                """SELECT * FROM products
                   WHERE UPPER(COALESCE(iban, '')) = ?
                      OR UPPER(COALESCE(isin, '')) = ?
                   LIMIT 1""",
                (normalized, normalized),
            ).fetchone()
        return None if row is None else _product_from_row(row)

    def list_products(self) -> list[Product]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM products ORDER BY name COLLATE NOCASE").fetchall()
        return [_product_from_row(row) for row in rows]

    def add_registry(self, registry: Registry) -> Registry:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO registries
                   (product_id, amount, recorded_on, labels_json, note, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (registry.product_id, str(registry.amount), registry.recorded_on.isoformat(),
                 _dump(registry.labels), registry.note, _dump(registry.metadata)),
            )
            return replace(registry, id=cursor.lastrowid)

    def delete_registry(self, registry_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM registries WHERE id = ?", (registry_id,))
            return cursor.rowcount > 0

    def delete_product(self, product_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM products WHERE id = ?", (product_id,))
            return cursor.rowcount > 0

    def list_registries(self, limit: int = 100) -> list[tuple[Registry, Product]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT r.*, p.name AS product_name, p.product_type, p.currency,
                          p.institution, p.labels_json AS product_labels_json,
                          p.metadata_json AS product_metadata_json, p.created_at AS product_created_at
                   FROM registries r JOIN products p ON p.id = r.product_id
                   ORDER BY r.recorded_on DESC, r.id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [(_registry_from_row(row), _product_from_joined_row(row)) for row in rows]

    def latest_registries(self) -> list[tuple[Registry, Product]]:
        """One newest registry per product, for a current balance snapshot."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT r.*, p.name AS product_name, p.product_type, p.currency,
                          p.institution, p.labels_json AS product_labels_json,
                          p.metadata_json AS product_metadata_json, p.created_at AS product_created_at
                   FROM registries r JOIN products p ON p.id = r.product_id
                   WHERE r.id = (SELECT r2.id FROM registries r2
                                 WHERE r2.product_id = p.id
                                 ORDER BY r2.recorded_on DESC, r2.id DESC LIMIT 1)
                   ORDER BY p.product_type, p.name COLLATE NOCASE"""
            ).fetchall()
        return [(_registry_from_row(row), _product_from_joined_row(row)) for row in rows]

    def import_excel(self, path: str | Path) -> int:
        dataframe = pd.read_excel(path)
        created_products = 0
        for row in dataframe.to_dict(orient="records"):
            name = str(row.get("name") or row.get("product") or row.get("product_name") or "").strip()
            if not name:
                continue

            product_type = _coerce_product_type(row.get("product_type") or row.get("type") or ProductType.OTHER.value)
            currency = str(row.get("currency") or "EUR").strip().upper() or "EUR"
            iban = _normalize_identifier(row.get("iban"))
            isin = _normalize_identifier(row.get("isin"))
            institution = row.get("institution")
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}

            existing = self.find_product_by_identifier(iban or isin)
            if existing is None:
                product = self.add_product(Product(
                    name=name,
                    product_type=product_type,
                    currency=currency,
                    institution=str(institution) if institution is not None else None,
                    metadata=metadata,
                    iban=iban,
                    isin=isin,
                ))
                created_products += 1
            else:
                product = existing

            raw_amount = row.get("amount")
            raw_date = row.get("date") or row.get("recorded_on") or row.get("fecha") or date.today().isoformat()
            try:
                amount = Decimal(str(raw_amount))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(f"Could not parse amount for product '{name}': {raw_amount!r}")
            recorded_on = _parse_date(raw_date)
            self.add_registry(Registry(product.id, amount, recorded_on, metadata=metadata))
        return created_products


def _normalize_identifier(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    normalized = str(value).strip().replace(" ", "")
    if normalized.lower() in {"", "nan", "none", "null"}:
        return None
    return normalized.upper() or None


def _coerce_product_type(value: object) -> ProductType:
    if isinstance(value, ProductType):
        return value
    raw = str(value).strip().lower().replace(" ", "_")
    try:
        return ProductType(raw)
    except ValueError:
        return ProductType.OTHER


def _parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value is None or str(value).strip() == "":
        return date.today()
    return date.fromisoformat(str(value).split(" ")[0])


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _product_from_row(row: sqlite3.Row) -> Product:
    return Product(id=row["id"], name=row["name"], product_type=ProductType(row["product_type"]),
                   currency=row["currency"], institution=row["institution"],
                   labels=tuple(json.loads(row["labels_json"])), metadata=json.loads(row["metadata_json"]),
                   iban=row["iban"], isin=row["isin"])


def _product_from_joined_row(row: sqlite3.Row) -> Product:
    return Product(id=row["product_id"], name=row["product_name"], product_type=ProductType(row["product_type"]),
                   currency=row["currency"], institution=row["institution"],
                   labels=tuple(json.loads(row["product_labels_json"])), metadata=json.loads(row["product_metadata_json"]))


def _registry_from_row(row: sqlite3.Row) -> Registry:
    return Registry(id=row["id"], product_id=row["product_id"], amount=Decimal(row["amount"]),
                    recorded_on=date.fromisoformat(row["recorded_on"]),
                    labels=tuple(json.loads(row["labels_json"])), note=row["note"],
                    metadata=json.loads(row["metadata_json"]))
