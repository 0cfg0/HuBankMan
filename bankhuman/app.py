"""Streamlit dashboard for the BankHuMan database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from bankhuman.analytics import (
    apply_dashboard_filters,
    current_by_institution,
    current_by_product,
    current_by_type,
    evolution_by_product,
    evolution_by_type,
    records_dataframe,
)
from bankhuman.database import Database
from bankhuman.models import Product, ProductType, Registry

DEFAULT_DATABASE = "data/bankhuman.db"


def launch() -> None:
    """Launch the Streamlit application through the installed console script."""
    database_path = None
    if "--database" in sys.argv:
        position = sys.argv.index("--database")
        if position + 1 < len(sys.argv):
            database_path = sys.argv[position + 1]
    if database_path:
        os.environ["BANKHUMAN_DATABASE"] = database_path

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve())],
        check=True,
        env=os.environ.copy(),
    )


def main() -> None:
    st.set_page_config(
        page_title="BankHuMan",
        page_icon="B",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { --ink: #17221f; --muted: #65736e; --mint: #c9f2dd; --orange: #f18f5b; }
        .block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
        [data-testid="stMetric"] { background: #f4f8f5; border: 1px solid #dce9e1; padding: 1rem; }
        h1, h2, h3 { color: var(--ink); letter-spacing: 0; }
        .hero { border-left: 6px solid var(--orange); padding: .4rem 0 .4rem 1rem; margin-bottom: 1.5rem; }
        .hero p { color: var(--muted); margin: .25rem 0 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    database_path = st.sidebar.text_input(
        "Database path",
        value=os.environ.get("BANKHUMAN_DATABASE", DEFAULT_DATABASE),
        help="The SQLite file is created automatically if it does not exist.",
    )
    database = Database(Path(database_path))
    database.initialize()

    st.markdown(
        '<div class="hero"><h1>BankHuMan</h1><p>Your financial position, with a little more breathing room.</p></div>',
        unsafe_allow_html=True,
    )
    management, current_state, evolution = st.tabs(["Management", "Current state", "Evolution"])
    with management:
        render_management(database)
    with current_state:
        render_current_state(database)
    with evolution:
        render_evolution(database)


def render_management(database: Database) -> None:
    products = database.list_products()
    records = database.list_registries(limit=None)
    st.subheader("Manage your records")
    st.caption(f"{len(products)} products · {len(records)} registry entries")

    product_tab, registry_tab, import_tab = st.tabs(["Products", "Registries", "Import"])
    with product_tab:
        render_product_management(database, products)
    with registry_tab:
        render_registry_management(database, products, records)
    with import_tab:
        render_import(database)


def render_product_management(database: Database, products: list[Product]) -> None:
    create, edit, remove = st.columns(3)
    with create:
        with st.form("add_product", clear_on_submit=True):
            st.markdown("#### Add product")
            name = st.text_input("Name")
            product_type = st.selectbox("Type", list(ProductType), format_func=lambda value: value.value.replace("_", " ").title())
            currency = st.text_input("Currency", "EUR", max_chars=3)
            institution = st.text_input("Institution")
            owner = st.text_input("Owner", "yo")
            labels = st.text_input("Labels", help="Comma-separated")
            iban = st.text_input("IBAN")
            isin = st.text_input("ISIN")
            metadata = st.text_area("Metadata JSON", "{}")
            if st.form_submit_button("Add product", type="primary"):
                try:
                    saved = database.add_product(_product_from_form(
                        name, product_type, currency, institution, owner, labels, iban, isin, metadata,
                    ))
                    st.success(f"Added {saved.name}.")
                    st.rerun()
                except (ValueError, json.JSONDecodeError) as error:
                    st.error(str(error))

    with edit:
        st.markdown("#### Edit product")
        if not products:
            st.info("Add a product to begin.")
        else:
            selected_id = st.selectbox("Product", [product.id for product in products], format_func=lambda value: next(product.name for product in products if product.id == value), key="edit_product_id")
            product = next(product for product in products if product.id == selected_id)
            with st.form("edit_product"):
                name = st.text_input("Name", product.name)
                product_type = st.selectbox("Type", list(ProductType), index=list(ProductType).index(product.product_type), format_func=lambda value: value.value.replace("_", " ").title())
                currency = st.text_input("Currency", product.currency, max_chars=3)
                institution = st.text_input("Institution", product.institution or "")
                owner = st.text_input("Owner", product.owner)
                labels = st.text_input("Labels", ", ".join(product.labels))
                iban = st.text_input("IBAN", product.iban or "")
                isin = st.text_input("ISIN", product.isin or "")
                metadata = st.text_area("Metadata JSON", json.dumps(product.metadata, sort_keys=True))
                if st.form_submit_button("Save changes", type="primary"):
                    try:
                        updated = database.update_product(_product_from_form(
                            name, product_type, currency, institution, owner, labels, iban, isin, metadata, product.id,
                        ))
                        st.success(f"Updated {updated.name}.")
                        st.rerun()
                    except (ValueError, json.JSONDecodeError) as error:
                        st.error(str(error))

    with remove:
        st.markdown("#### Delete product")
        if products:
            selected_id = st.selectbox("Product to remove", [product.id for product in products], format_func=lambda value: next(product.name for product in products if product.id == value), key="remove_product_id")
            st.warning("Deleting a product also deletes its registry history.")
            if st.button("Delete product", type="secondary"):
                st.session_state["confirm_product_delete"] = selected_id
            if st.session_state.get("confirm_product_delete") == selected_id:
                st.error("This cannot be undone.")
                if st.button("Confirm deletion", key="confirm_product"):
                    database.delete_product(selected_id)
                    st.session_state.pop("confirm_product_delete", None)
                    st.rerun()
        else:
            st.info("No products to remove.")

    if products:
        st.markdown("#### Product register")
        st.dataframe(pd.DataFrame([_product_row(product) for product in products]), use_container_width=True, hide_index=True)


def render_registry_management(database: Database, products: list[Product], records: list[tuple[Registry, Product]]) -> None:
    add, remove = st.columns([1, 1])
    with add:
        st.markdown("#### Add registry")
        if not products:
            st.info("Add a product before recording a value.")
        else:
            with st.form("add_registry", clear_on_submit=True):
                product_id = st.selectbox("Product", [product.id for product in products], format_func=lambda value: next(product.name for product in products if product.id == value))
                amount = st.text_input("Amount", placeholder="Negative for debt")
                recorded_on = st.date_input("Date", date.today())
                labels = st.text_input("Labels")
                note = st.text_input("Note")
                metadata = st.text_area("Metadata JSON", "{}")
                if st.form_submit_button("Add registry", type="primary"):
                    try:
                        registry = Registry(
                            product_id=product_id,
                            amount=Decimal(amount),
                            recorded_on=recorded_on,
                            labels=_labels(labels),
                            note=note.strip() or None,
                            metadata=_json_object(metadata),
                        )
                        database.add_registry(registry)
                        st.success("Registry saved.")
                        st.rerun()
                    except (ValueError, ArithmeticError, json.JSONDecodeError) as error:
                        st.error(str(error))

    with remove:
        st.markdown("#### Delete registry")
        if not records:
            st.info("No registry entries yet.")
        else:
            registry_id = st.selectbox("Entry", [registry.id for registry, _ in records], format_func=lambda value: _registry_label(value, records))
            if st.button("Delete registry"):
                st.session_state["confirm_registry_delete"] = registry_id
            if st.session_state.get("confirm_registry_delete") == registry_id:
                if st.button("Confirm deletion", key="confirm_registry"):
                    database.delete_registry(registry_id)
                    st.session_state.pop("confirm_registry_delete", None)
                    st.rerun()

    if records:
        st.markdown("#### Registry history")
        st.dataframe(pd.DataFrame([_registry_row(registry, product) for registry, product in records]), use_container_width=True, hide_index=True)


def render_import(database: Database) -> None:
    st.markdown("#### Import positions")
    st.caption("Upload an Excel workbook in the same formats accepted by the existing importer.")
    uploaded = st.file_uploader("Excel file", type=["xlsx", "xls"])
    if uploaded is not None and st.button("Import workbook", type="primary"):
        suffix = Path(uploaded.name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(uploaded.getvalue())
            temporary_path = Path(temporary.name)
        try:
            created = database.import_excel(temporary_path)
            st.success(f"Imported workbook: {created} new products.")
            st.rerun()
        except (ValueError, OSError) as error:
            st.error(str(error))
        finally:
            temporary_path.unlink(missing_ok=True)


def render_current_state(database: Database) -> None:
    current = apply_dashboard_filters(records_dataframe(database.latest_registries()))
    st.subheader("Current position")
    if current.empty:
        st.info("No dashboard values yet. Add a registry entry in Management.")
        return

    currencies = sorted(current["currency"].unique())
    metric_columns = st.columns(len(currencies))
    for column, currency in zip(metric_columns, currencies):
        amount = current.loc[current["currency"] == currency, "amount"].sum()
        column.metric(f"Current {currency}", f"{amount:,.2f}")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.bar(current_by_type(current), x="currency", y="amount", color="product_type", barmode="stack", title="By currency and product type"),
            use_container_width=True,
        )
    with right:
        product_breakdown = current_by_product(current)
        st.plotly_chart(
            px.pie(product_breakdown, names="label", values="amount", hole=0.45, title="Current distribution"),
            use_container_width=True,
        )
    institution = current_by_institution(current)
    st.plotly_chart(
        px.bar(institution, x="label", y="amount", color="product_type", barmode="stack", title="By institution and product type"),
        use_container_width=True,
    )


def render_evolution(database: Database) -> None:
    historical = apply_dashboard_filters(records_dataframe(database.list_registries(limit=None)))
    st.subheader("Evolution")
    if historical.empty:
        st.info("No historical values yet. Add registry entries in Management.")
        return

    product_lines = evolution_by_product(historical)
    type_lines = evolution_by_type(historical)
    left, right = st.columns(2)
    with left:
        figure = px.line(product_lines, x="date", y="amount", color="label", line_dash="series", markers=True, title="Evolution by product", hover_data=["currency"])
        figure.update_traces(selector={"line": {"dash": "dash"}}, line={"width": 3})
        st.plotly_chart(figure, use_container_width=True)
    with right:
        figure = px.line(type_lines, x="date", y="amount", color="label", line_dash="series", markers=True, title="Evolution by product type", hover_data=["currency"])
        figure.update_traces(selector={"line": {"dash": "dash"}}, line={"width": 3})
        st.plotly_chart(figure, use_container_width=True)


def _product_from_form(name: str, product_type: ProductType, currency: str, institution: str, owner: str, labels: str, iban: str, isin: str, metadata: str, product_id: int | None = None) -> Product:
    return Product(
        id=product_id,
        name=name,
        product_type=product_type,
        currency=currency.strip().upper(),
        institution=institution.strip() or None,
        owner=owner,
        labels=_labels(labels),
        iban=iban,
        isin=isin,
        metadata=_json_object(metadata),
    )


def _json_object(raw: str) -> dict[str, object]:
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("Metadata must be a JSON object.")
    return value


def _labels(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))


def _product_row(product: Product) -> dict[str, object]:
    return {
        "ID": product.id,
        "Name": product.name,
        "Type": product.product_type.value,
        "Currency": product.currency,
        "Institution": product.institution or "",
        "Owner": product.owner,
        "Labels": ", ".join(product.labels),
    }


def _registry_row(registry: Registry, product: Product) -> dict[str, object]:
    return {
        "ID": registry.id,
        "Date": registry.recorded_on,
        "Product": product.name,
        "Amount": registry.amount,
        "Currency": product.currency,
        "Labels": ", ".join(registry.labels),
        "Note": registry.note or "",
    }


def _registry_label(registry_id: int, records: list[tuple[Registry, Product]]) -> str:
    registry, product = next(item for item in records if item[0].id == registry_id)
    return f"{registry.recorded_on} · {product.name} · {registry.amount} {product.currency}"


if __name__ == "__main__":
    main()
