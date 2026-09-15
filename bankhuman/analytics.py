"""Data preparation for the dashboard charts."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pandas as pd

from .models import Product, ProductType, Registry

Record = tuple[Registry, Product]


def records_dataframe(records: Iterable[Record]) -> pd.DataFrame:
    """Convert database records into chart-friendly rows."""
    rows = [
        {
            "registry_id": registry.id,
            "product_id": product.id,
            "date": registry.recorded_on,
            "amount": float(registry.amount),
            "currency": product.currency,
            "product": product.name,
            "product_type": product.product_type.value,
            "owner": product.owner,
            "institution": product.institution or "Unknown",
        }
        for registry, product in records
    ]
    return pd.DataFrame(rows, columns=[
        "registry_id", "product_id", "date", "amount", "currency", "product",
        "product_type", "owner", "institution",
    ])


def apply_dashboard_filters(
    dataframe: pd.DataFrame,
    owner: str = "yo",
    exclude_other: bool = True,
    exclude_casa: bool = True,
) -> pd.DataFrame:
    """Apply the defaults used by the live analysis notebook."""
    filtered = dataframe.copy()
    if owner:
        filtered = filtered[filtered["owner"].str.casefold() == owner.casefold()]
    if exclude_other:
        filtered = filtered[filtered["product_type"] != ProductType.OTHER.value]
    if exclude_casa:
        filtered = filtered[filtered["product"].str.casefold() != "casa"]
    return filtered.reset_index(drop=True)


def current_by_type(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aggregate current values by currency and product type."""
    return (
        dataframe.groupby(["currency", "product_type"], as_index=False)["amount"]
        .sum()
    )


def current_by_institution(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aggregate current values by institution and product type."""
    result = (
        dataframe.groupby(["institution", "currency", "product_type"], as_index=False)["amount"]
        .sum()
    )
    result["label"] = (
        result["institution"] + " (" + result["currency"] + ")"
    )
    return result


def current_by_product(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aggregate current values by product and currency."""
    result = (
        dataframe.groupby(["product", "currency", "product_type"], as_index=False)["amount"]
        .sum()
    )
    result["label"] = result["product"] + " (" + result["currency"] + ")"
    return result


def _latest_at_snapshots(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe.copy()

    snapshots: list[pd.DataFrame] = []
    for snapshot_date in sorted(dataframe["date"].unique()):
        latest = (
            dataframe[dataframe["date"] <= snapshot_date]
            .sort_values(["date", "registry_id"])
            .drop_duplicates("product_id", keep="last")
            .copy()
        )
        latest["date"] = snapshot_date
        snapshots.append(latest)
    return pd.concat(snapshots, ignore_index=True)


def evolution_by_product(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return product lines plus currency-specific total lines."""
    snapshots = _latest_at_snapshots(dataframe)
    if snapshots.empty:
        return pd.DataFrame(columns=["date", "amount", "label", "series", "currency"])

    product_lines = (
        snapshots.groupby(["date", "product", "currency"], as_index=False)["amount"]
        .sum()
    )
    product_lines["label"] = product_lines["product"] + " (" + product_lines["currency"] + ")"
    product_lines["series"] = "Product"

    totals = (
        snapshots.groupby(["date", "currency"], as_index=False)["amount"]
        .sum()
    )
    totals["product"] = "Total"
    totals["label"] = "Total (" + totals["currency"] + ")"
    totals["series"] = "Total"
    return pd.concat([product_lines, totals], ignore_index=True, sort=False)


def evolution_by_type(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return product-type lines plus currency-specific total lines."""
    snapshots = _latest_at_snapshots(dataframe)
    if snapshots.empty:
        return pd.DataFrame(columns=["date", "amount", "label", "series", "currency"])

    type_lines = (
        snapshots.groupby(["date", "product_type", "currency"], as_index=False)["amount"]
        .sum()
    )
    type_lines["label"] = (
        type_lines["product_type"] + " (" + type_lines["currency"] + ")"
    )
    type_lines["series"] = "Product type"

    totals = (
        type_lines.groupby(["date", "currency"], as_index=False)["amount"]
        .sum()
    )
    totals["product_type"] = "Total"
    totals["label"] = "Total (" + totals["currency"] + ")"
    totals["series"] = "Total"
    return pd.concat([type_lines, totals], ignore_index=True, sort=False)


def decimal_total(values: Iterable[Decimal]) -> Decimal:
    """Sum monetary values without introducing floating-point arithmetic."""
    return sum(values, Decimal("0"))
