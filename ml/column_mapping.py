"""
Column auto-mapping & derivation for uploaded sales/order CSVs.

The rest of the pipeline (db schema, SQL queries, RFM, churn model, KPIs)
all assume one fixed 16-column "orders" schema. Real-world CSVs almost
never use those exact header names (e.g. "Order Date" vs "order_date",
"Total" vs "revenue", "CustomerID" vs "customer_id"), so previously any
upload that didn't match the demo file byte-for-byte on headers would
silently end up with every "required" column empty, get dropped by the
critical-field cleaning step, and leave the dashboard showing an empty /
all-zero dataset instead of a real error.

This module renames recognizable columns onto the canonical schema and
derives every remaining field with a best-effort fallback (revenue,
unit_price, quantity, ids, names, even the order date itself) so that ANY
tabular business file can be loaded and produce a working dashboard. When
a concept genuinely has no equivalent in the file (e.g. no monetary column
at all), we don't fabricate the whole file back to zero rows -- we pick
the closest available substitute and clearly flag the assumption in the
quality report so the person knows which numbers are exact and which are
approximations.
"""

import re
import numpy as np
import pandas as pd

CANONICAL_COLUMNS = [
    "order_id", "order_date", "customer_id", "customer_name", "region",
    "product_id", "product_name", "category", "quantity", "unit_price",
    "discount_pct", "revenue", "cost", "profit", "payment_method", "order_status",
]

# Canonical column -> list of normalized aliases we recognize.
# Order matters: matched earlier are claimed first so a source column is
# never mapped to two different targets.
ALIASES = {
    "order_id": [
        "order_id", "orderid", "order_no", "orderno", "order_number",
        "transaction_id", "transactionid", "invoice_id", "invoice_no",
        "invoiceno", "sale_id", "saleid", "id",
    ],
    "order_date": [
        "order_date", "orderdate", "date", "purchase_date", "purchasedate",
        "order_purchase_timestamp", "transaction_date", "invoice_date",
        "sale_date", "order_time", "timestamp", "created_at", "createdat",
    ],
    "customer_id": [
        "customer_id", "customerid", "cust_id", "custid", "client_id",
        "clientid", "user_id", "userid", "buyer_id",
    ],
    "customer_name": [
        "customer_name", "customername", "cust_name", "custname",
        "client_name", "full_name", "fullname", "buyer_name", "name",
        "customer",
    ],
    "region": [
        "region", "state", "country", "location", "zone", "area", "city",
    ],
    "product_id": [
        "product_id", "productid", "item_id", "itemid", "sku", "prod_id",
    ],
    "product_name": [
        "product_name", "productname", "item_name", "itemname", "product",
        "item", "product_title", "title",
    ],
    "category": [
        "category", "product_category", "productcategory", "item_category",
        "segment", "type", "genre",
    ],
    "quantity": [
        "quantity", "qty", "order_quantity", "orderquantity", "units",
        "unit_count", "quantity_ordered",
    ],
    "unit_price": [
        "unit_price", "unitprice", "price", "product_price", "productprice",
        "price_per_unit", "cost_per_unit", "item_price",
    ],
    "discount_pct": [
        "discount_pct", "discount", "discount_percentage", "discountrate",
        "discount_rate",
    ],
    "revenue": [
        "revenue", "sales", "amount", "total", "total_amount",
        "totalamount", "totalsales", "total_sales", "order_value",
        "ordervalue", "sale_amount", "net_sales", "grand_total",
        "line_total", "total_price",
    ],
    "cost": [
        "cost", "cogs", "cost_price", "costprice", "total_cost",
    ],
    "profit": [
        "profit", "profit_loss", "net_profit", "margin_amount",
    ],
    "payment_method": [
        "payment_method", "paymentmethod", "payment_type", "paymenttype",
    ],
    "order_status": [
        "order_status", "orderstatus", "status", "return_status",
        "delivery_status",
    ],
}

# If no exact alias matches, fall back to "column name contains this
# substring" for a few high-value, low-ambiguity targets only.
FUZZY_CONTAINS = {
    "order_date": ["date", "timestamp"],
    "revenue": ["revenue", "sales", "amount", "total"],
    "customer_id": ["custid", "clientid", "userid"],
}


def _normalize(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"\(.*?\)", "", name)          # drop "(k$)" etc.
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def map_columns(df: pd.DataFrame):
    """Rename recognizable columns onto the canonical schema.

    Returns (renamed_df, mapping) where mapping is
    {canonical_name: original_column_name_or_None}.
    """
    df = df.copy()
    normalized = {col: _normalize(col) for col in df.columns}
    available = dict(normalized)  # normalized -> original, shrinks as we claim columns
    norm_to_orig = {v: k for k, v in normalized.items()}

    mapping = {}
    rename = {}

    for target, aliases in ALIASES.items():
        found_orig = None
        for alias in aliases:
            if alias in available.values():
                found_orig = norm_to_orig[alias]
                break
        if found_orig is None:
            for substr in FUZZY_CONTAINS.get(target, []):
                for norm, orig in list(available.items()):
                    if substr in norm:
                        found_orig = orig
                        break
                if found_orig:
                    break
        if found_orig is not None:
            mapping[target] = found_orig
            rename[found_orig] = target
            # this original column is now claimed
            available = {k: v for k, v in available.items() if v != found_orig}
        else:
            mapping[target] = None

    df = df.rename(columns=rename)
    # If renaming created duplicate target columns (shouldn't happen, but
    # be defensive), keep the first occurrence.
    df = df.loc[:, ~df.columns.duplicated()]
    return df, mapping


def derive_missing_fields(df: pd.DataFrame, mapping: dict, report: dict):
    """Fill in every field the pipeline needs, using the best available
    stand-in when a real column doesn't exist, so the file always loads.
    Mutates `report` with a human-readable list of assumptions made."""
    assumptions = []
    approximated = []  # which concepts are approximate, for the UI to flag

    for col in ("quantity", "unit_price", "discount_pct", "revenue", "cost", "profit"):
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- order_date: synthesize sequential dates if there's truly no date column ---
    if mapping.get("order_date") is None:
        n = max(len(df), 1)
        synthetic = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n, freq="D")
        df["order_date"] = synthetic.strftime("%Y-%m-%d")
        assumptions.append(
            "No date column found — assumed one sequential day per row so charts can "
            "render. Time-based figures (monthly trend, growth, recency) aren't meaningful for this file."
        )
        approximated.append("dates")

    # quantity: default to 1 unit per row if not present at all
    if mapping.get("quantity") is None:
        df["quantity"] = df["quantity"].fillna(1)
        assumptions.append("No quantity column found — assumed 1 unit per row.")

    # --- revenue: derive from quantity × unit price, or fall back to the
    # best available numeric column, or a flat placeholder as a last resort ---
    if mapping.get("revenue") is not None:
        pass  # already a real column, just numeric-coerced above
    elif mapping.get("unit_price") is not None:
        disc = df["discount_pct"].fillna(0)
        disc = np.where(disc > 1, disc / 100.0, disc)  # tolerate "20" meaning 20%
        df["revenue"] = df["quantity"].fillna(1) * df["unit_price"] * (1 - disc)
        assumptions.append("No revenue/amount column found — derived revenue as quantity × unit price.")
    else:
        claimed = {v for v in mapping.values() if v}
        candidates = []
        for c in df.columns:
            if c in claimed or c in CANONICAL_COLUMNS:
                continue
            s = pd.to_numeric(df[c], errors="coerce")
            if s.notna().sum() > 0:
                candidates.append((c, s))
        if candidates:
            best_col, best_series = max(candidates, key=lambda t: t[1].fillna(0).abs().sum())
            df["revenue"] = best_series.abs().fillna(0)
            assumptions.append(
                f"No revenue, price, or amount column found — used the numeric column "
                f"'{best_col}' as a stand-in for order value. Monetary totals for this "
                f"file are approximate, not real currency figures."
            )
        else:
            df["revenue"] = 1.0
            assumptions.append(
                "No numeric monetary column found anywhere in this file — revenue was "
                "set to a flat placeholder so the dashboard can still render. Monetary "
                "totals are not meaningful for this file; treat counts (orders, customers) as the reliable numbers."
            )
        approximated.append("revenue")

    # unit_price: derive from revenue / quantity whenever it's still missing
    if mapping.get("unit_price") is None:
        qty = df["quantity"].replace(0, np.nan).fillna(1)
        df["unit_price"] = (df["revenue"] / qty).round(2)
        if mapping.get("revenue") is not None:
            assumptions.append("No unit price column found — derived from revenue ÷ quantity.")

    # tolerate discount given as "20" instead of "0.2"
    if mapping.get("discount_pct") is not None:
        df["discount_pct"] = np.where(df["discount_pct"] > 1, df["discount_pct"] / 100.0, df["discount_pct"])

    if mapping.get("order_id") is None:
        df["order_id"] = ["ORD" + str(i + 1).zfill(6) for i in range(len(df))]
        assumptions.append("No order ID column found — generated one row per order.")

    if mapping.get("customer_id") is None:
        if mapping.get("customer_name") is not None:
            # Reuse the name as the identifier so repeat customers still
            # aggregate correctly, instead of treating every row as a new
            # customer (which would silently break RFM/repeat-rate metrics).
            df["customer_id"] = df["customer_name"].astype(str)
            assumptions.append("No customer ID column found — used customer name as the identifier.")
        else:
            df["customer_id"] = ["CUST" + str(i + 1).zfill(6) for i in range(len(df))]
            assumptions.append("No customer ID column found — treated each row as a separate customer.")

    if mapping.get("customer_name") is None:
        if "customer_id" in df.columns:
            df["customer_name"] = df["customer_id"].astype(str)
        else:
            df["customer_name"] = "Unknown Customer"
        assumptions.append("No customer name column found — used customer ID as the name.")

    if mapping.get("product_id") is None:
        if mapping.get("product_name") is not None:
            df["product_id"] = df[mapping["product_name"]] if mapping["product_name"] in df.columns else df.get("product_name", "GEN-0001")
        else:
            df["product_id"] = "GEN-0001"

    if mapping.get("product_name") is None:
        df["product_name"] = df["category"] if "category" in df.columns and mapping.get("category") else "General Item"
        assumptions.append("No product name column found — used a generic placeholder.")

    report["column_mapping"] = {k: v for k, v in mapping.items() if v}
    report["assumptions"] = assumptions
    report["approximated_fields"] = approximated
    return df


def check_usable(mapping: dict) -> str:
    """Historically used to reject files with no recognizable date/money
    column. The pipeline now derives sensible stand-ins for both instead
    (see derive_missing_fields), so this always returns None — kept only
    so any external caller importing it doesn't break."""
    return None
