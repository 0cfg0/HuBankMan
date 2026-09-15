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


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, factory=_Connection)
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
                    owner TEXT NOT NULL DEFAULT 'yo',
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
            for column_name in ("iban", "isin", "owner"):
                if column_name not in columns:
                    definition = "TEXT NOT NULL DEFAULT 'yo'" if column_name == "owner" else "TEXT"
                    db.execute(f"ALTER TABLE products ADD COLUMN {column_name} {definition}")

    def add_product(self, product: Product) -> Product:
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO products
                   (name, product_type, currency, institution, labels_json, metadata_json, iban, isin, owner)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (product.name.strip(), product.product_type.value, product.currency.upper(),
                 product.institution, _dump(product.labels), _dump(product.metadata),
                 product.iban, product.isin, product.owner),
            )
            return replace(product, id=cursor.lastrowid)

    def update_product(self, product: Product) -> Product:
        if product.id is None:
            raise ValueError("A product must be saved before it can be updated.")
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE products
                   SET name = ?, product_type = ?, currency = ?, institution = ?,
                       labels_json = ?, metadata_json = ?, iban = ?, isin = ?, owner = ?
                   WHERE id = ?""",
                (product.name.strip(), product.product_type.value, product.currency.upper(),
                 product.institution, _dump(product.labels), _dump(product.metadata),
                 product.iban, product.isin, product.owner, product.id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Product #{product.id} does not exist.")
        return replace(product, id=product.id)

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

    def list_registries(self, limit: int | None = 100) -> list[tuple[Registry, Product]]:
        with self.connect() as db:
            query = """SELECT r.*, p.name AS product_name, p.product_type, p.currency,
                              p.institution, p.labels_json AS product_labels_json,
                              p.metadata_json AS product_metadata_json, p.iban AS product_iban,
                              p.isin AS product_isin, p.owner AS product_owner,
                              p.created_at AS product_created_at
                       FROM registries r JOIN products p ON p.id = r.product_id
                       ORDER BY r.recorded_on DESC, r.id DESC"""
            rows = db.execute(query if limit is None else query + " LIMIT ?", () if limit is None else (limit,)).fetchall()
        return [(_registry_from_row(row), _product_from_joined_row(row)) for row in rows]

    def latest_registries(self) -> list[tuple[Registry, Product]]:
        """One newest registry per product, for a current balance snapshot."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT r.*, p.name AS product_name, p.product_type, p.currency,
                          p.institution, p.labels_json AS product_labels_json,
                          p.metadata_json AS product_metadata_json, p.iban AS product_iban,
                          p.isin AS product_isin, p.owner AS product_owner,
                          p.created_at AS product_created_at
                   FROM registries r JOIN products p ON p.id = r.product_id
                   WHERE r.id = (SELECT r2.id FROM registries r2
                                 WHERE r2.product_id = p.id
                                 ORDER BY r2.recorded_on DESC, r2.id DESC LIMIT 1)
                   ORDER BY p.product_type, p.name COLLATE NOCASE"""
            ).fetchall()
        return [(_registry_from_row(row), _product_from_joined_row(row)) for row in rows]

    def import_excel(self, path: str | Path) -> int:
        dataframe = pd.read_excel(path)
        normalized_columns = {str(column).strip().lower() for column in dataframe.columns}
        if "name" not in normalized_columns and "alias" not in normalized_columns:
            return self._import_position_global(path)
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

    def _import_position_global(self, path: str | Path) -> int:
        created_products = 0
        section = None
        frame = pd.read_excel(path, header=None)
        rows = [
            [str(value).strip() if pd.notna(value) else "" for value in row]
            for row in frame.itertuples(index=False, name=None)
        ]
        for row_index, values in enumerate(rows):
            first_value = values[0].lower() if values else ""
            if first_value.startswith("cuentas"):
                section = "bank_account"
            elif first_value.startswith("fondos") or first_value.startswith("ahorro e inversión"):
                section = "fund"
            elif first_value.startswith("depósitos"):
                section = "deposit"
            elif first_value.startswith("valores"):
                section = "investment"
            elif first_value.startswith("tajetas") or first_value.startswith("tarjetas"):
                section = "credit_card"
            elif first_value.startswith("financiacion"):
                section = "loan"
            elif first_value.startswith("seguros"):
                section = "insurance"
            elif first_value.startswith("patrimonio inmobiliario"):
                section = "property"

            lowered_values = {value.lower() for value in values}
            if not section or not ({"alias", "nombre vivienda"} & lowered_values):
                continue

            headers = [value.lower() for value in values]
            for data_values in rows[row_index + 1:]:
                if not any(data_values):
                    break
                if data_values[0].lower() in {"alias", "fondos", "depósitos", "valores", "hipotecas y préstamos"}:
                    break
                record = dict(zip(headers, data_values))
                amount_value = (
                    record.get("disponible")
                    or record.get("valoración")
                    or record.get("dispuesto")
                    or record.get("pendiente")
                )
                if not amount_value or amount_value in {"-", "'-"}:
                    continue
                amount = _parse_amount(amount_value)
                currency = record.get("divisa") or "EUR"
                isin = _normalize_identifier(record.get("isin"))
                institution = record.get("banco") or None
                alias = record.get("alias") or record.get("nombre vivienda") or "Imported position"
                iban = _normalize_identifier(record.get("iban"))
                if section == "bank_account" and len(alias) > 15 and alias[:2].isalpha():
                    iban = _normalize_identifier(alias)
                    name = f"{institution or 'Bank account'} ({iban[-4:]})"
                else:
                    name = alias
                existing = self.find_product_by_identifier(iban or isin)
                if existing is None:
                    for product in self.list_products():
                        if product.name.casefold() == name.casefold() and product.institution == institution:
                            existing = product
                            break
                if existing is None:
                    product = self.add_product(Product(
                        name=name,
                        product_type={
                            "bank_account": ProductType.BANK_ACCOUNT,
                            "fund": ProductType.FUND,
                            "investment": ProductType.INVESTMENT,
                            "credit_card": ProductType.CREDIT_CARD,
                            "loan": ProductType.LOAN,
                            "property": ProductType.OTHER,
                        }.get(section, ProductType.OTHER),
                        currency=currency,
                        institution=institution,
                        iban=iban,
                        isin=isin,
                        metadata={"import_section": section, "source_alias": alias},
                    ))
                    created_products += 1
                else:
                    product = existing
                self.add_registry(Registry(product.id, amount, date.today(), metadata={"source": Path(path).name}))
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


def _parse_amount(value: object) -> Decimal:
    normalized = str(value).strip().replace("'", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    return Decimal(normalized)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _product_from_row(row: sqlite3.Row) -> Product:
    return Product(id=row["id"], name=row["name"], product_type=ProductType(row["product_type"]),
                   currency=row["currency"], institution=row["institution"],
                   labels=tuple(json.loads(row["labels_json"])), metadata=json.loads(row["metadata_json"]),
                   iban=row["iban"], isin=row["isin"], owner=row["owner"])


def _product_from_joined_row(row: sqlite3.Row) -> Product:
    return Product(id=row["product_id"], name=row["product_name"], product_type=ProductType(row["product_type"]),
                   currency=row["currency"], institution=row["institution"],
                   labels=tuple(json.loads(row["product_labels_json"])), metadata=json.loads(row["product_metadata_json"]),
                   iban=row["product_iban"], isin=row["product_isin"], owner=row["product_owner"])


def _registry_from_row(row: sqlite3.Row) -> Registry:
    return Registry(id=row["id"], product_id=row["product_id"], amount=Decimal(row["amount"]),
                    recorded_on=date.fromisoformat(row["recorded_on"]),
                    labels=tuple(json.loads(row["labels_json"])), note=row["note"],
                    metadata=json.loads(row["metadata_json"]))
