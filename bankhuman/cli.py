"""A deliberately small, friendly terminal interface."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .database import Database
from .models import Product, ProductType, Registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Track personal financial products locally.")
    parser.add_argument("--database", default="data/bankhuman.db", help="SQLite database path")
    args = parser.parse_args()
    database = Database(Path(args.database))
    database.initialize()
    run_menu(database)


def run_menu(database: Database) -> None:
    actions = {
        "1": ("Add a product", lambda: add_product_prompt(database)),
        "2": ("Add a registry", lambda: add_registry_prompt(database)),
        "3": ("List products", lambda: print_products(database)),
        "4": ("List registries", lambda: print_registries(database)),
        "5": ("Show current summary", lambda: print_summary(database)),
        "6": ("Delete a registry", lambda: delete_registry_prompt(database)),
        "7": ("Delete a product", lambda: delete_product_prompt(database)),
        "8": ("Import from Excel", lambda: import_excel_prompt(database)),
        "9": ("Edit a product", lambda: edit_product_prompt(database)),
    }
    while True:
        print("\nBankHuMan")
        for key, (label, _) in actions.items():
            print(f"  {key}. {label}")
        print("  0. Exit")
        choice = input("Choose an action: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if not action:
            print("Please enter one of the displayed numbers.")
            continue
        try:
            action[1]()
        except (ValueError, InvalidOperation, json.JSONDecodeError) as error:
            print(f"Could not save that: {error}")


def add_product_prompt(database: Database) -> None:
    print("\nNew product")
    print("Types: " + ", ".join(kind.value for kind in ProductType))
    product = Product(
        name=_required("Name"),
        product_type=ProductType(input("Type: ").strip().lower()),
        currency=(input("Currency [EUR]: ").strip() or "EUR").upper(),
        institution=_optional("Institution"),
        labels=_labels(input("Labels (comma-separated, optional): ")),
        metadata=_metadata(),
    )
    saved = database.add_product(product)
    print(f"Saved product #{saved.id}: {saved.name}")


def add_registry_prompt(database: Database) -> None:
    products = database.list_products()
    if not products:
        print("Add a product before adding a registry.")
        return
    print("\nProducts")
    for product in products:
        print(f"  {product.id}. {product.name} ({product.product_type.value}, {product.currency})")
    product_id = int(_required("Product ID"))
    if product_id not in {product.id for product in products}:
        raise ValueError("That product ID does not exist.")
    amount = Decimal(_required("Amount (negative for debt)"))
    recorded = input(f"Date [{date.today().isoformat()}]: ").strip() or date.today().isoformat()
    saved = database.add_registry(Registry(
        product_id=product_id, amount=amount, recorded_on=date.fromisoformat(recorded),
        labels=_labels(input("Labels (comma-separated, optional): ")),
        note=_optional("Note"), metadata=_metadata(),
    ))
    print(f"Saved registry #{saved.id}.")


def print_products(database: Database) -> None:
    products = database.list_products()
    if not products:
        print("No products yet.")
        return
    print("\nID  Type          Currency  Name")
    for product in products:
        print(f"{product.id:<3} {product.product_type.value:<13} {product.currency:<9} {product.name}")


def print_registries(database: Database) -> None:
    records = database.list_registries()
    if not records:
        print("No registries yet.")
        return
    print("\nDate        Product                     Amount       Labels")
    for registry, product in records:
        print(f"{registry.recorded_on}  {product.name[:26]:<26}  {registry.amount:>12} {product.currency}  {', '.join(registry.labels)}")


def print_summary(database: Database) -> None:
    records = database.latest_registries()
    if not records:
        print("No registry values yet.")
        return
    totals: dict[tuple[ProductType, str], Decimal] = {}
    print("\nLatest value per product")
    for registry, product in records:
        key = (product.product_type, product.currency)
        totals[key] = totals.get(key, Decimal("0")) + registry.amount
        print(f"{product.name:<30} {registry.amount:>12} {product.currency}  ({registry.recorded_on})")
    print("\nTotals (currencies are intentionally kept separate)")
    for (kind, currency), amount in totals.items():
        print(f"{kind.value:<14} {amount:>12} {currency}")


def delete_registry_prompt(database: Database) -> None:
    records = database.list_registries()
    if not records:
        print("No registries yet.")
        return
    print("\nRegistries")
    for registry, product in records:
        print(f"  {registry.id}. {registry.recorded_on}  {product.name}  {registry.amount} {product.currency}")
    registry_id = int(_required("Registry ID"))
    confirmation = input("Type DELETE to confirm removal: ").strip()
    if confirmation != "DELETE":
        print("Deletion cancelled.")
        return
    if database.delete_registry(registry_id):
        print(f"Deleted registry #{registry_id}.")
        return
    raise ValueError("That registry ID does not exist.")


def delete_product_prompt(database: Database) -> None:
    products = database.list_products()
    if not products:
        print("No products yet.")
        return
    print("\nProducts")
    for product in products:
        print(f"  {product.id}. {product.name} ({product.product_type.value}, {product.currency})")
    product_id = int(_required("Product ID"))
    confirmation = input("Type DELETE to confirm removal: ").strip()
    if confirmation != "DELETE":
        print("Deletion cancelled.")
        return
    if database.delete_product(product_id):
        print(f"Deleted product #{product_id}.")
        return
    raise ValueError("That product ID does not exist.")


def edit_product_prompt(database: Database) -> None:
    products = database.list_products()
    if not products:
        print("No products yet.")
        return
    print("\nProducts")
    for product in products:
        print(f"  {product.id}. {product.name} ({product.product_type.value}, {product.currency})")
    product_id = int(_required("Product ID"))
    product = next((item for item in products if item.id == product_id), None)
    if product is None:
        raise ValueError("That product ID does not exist.")

    print("Press Enter to keep the current value.")
    name = input(f"Name [{product.name}]: ").strip() or product.name
    raw_type = input(f"Type [{product.product_type.value}]: ").strip().lower()
    product_type = ProductType(raw_type or product.product_type.value)
    currency = input(f"Currency [{product.currency}]: ").strip().upper() or product.currency
    institution = input(f"Institution [{product.institution or ''}]: ").strip() or product.institution
    labels = _labels(input(f"Labels (comma-separated) [{', '.join(product.labels)}]: ")) or product.labels
    metadata = _metadata_with_default(product.metadata)
    iban = input(f"IBAN [{product.iban or ''}]: ").strip() or product.iban
    isin = input(f"ISIN [{product.isin or ''}]: ").strip() or product.isin
    owner = input(f"Owner [{product.owner}]: ").strip() or product.owner

    updated = database.update_product(Product(
        id=product.id,
        name=name,
        product_type=product_type,
        currency=currency,
        institution=institution,
        labels=labels,
        metadata=metadata,
        iban=iban,
        isin=isin,
        owner=owner,
    ))
    print(f"Updated product #{updated.id}: {updated.name}")


def import_excel_prompt(database: Database) -> None:
    path = Path(input("Excel file path: ").strip())
    created = database.import_excel(path)
    print(f"Imported Excel file: created {created} new products and matched registry rows.")


def _required(label: str) -> str:
    value = input(f"{label}: ").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    return value


def _optional(label: str) -> str | None:
    return input(f"{label} (optional): ").strip() or None


def _labels(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(label.strip() for label in raw.split(",") if label.strip()))


def _metadata() -> dict[str, object]:
    raw = input("Metadata as JSON (optional): ").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Metadata must be a JSON object, e.g. {\"ticker\": \"VWCE\"}.")
    return value


def _metadata_with_default(current: dict[str, object]) -> dict[str, object]:
    raw = input(f"Metadata as JSON [{json.dumps(current, sort_keys=True)}]: ").strip()
    if not raw:
        return current
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Metadata must be a JSON object, e.g. {\"ticker\": \"VWCE\"}.")
    return value
