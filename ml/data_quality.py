"""
Automated Data Quality Monitor + Cleaning pipeline.
Validates an uploaded (or generated) sales CSV, reports a quality score,
and returns a cleaned DataFrame ready to load into SQLite.
"""

import pandas as pd
import numpy as np

from ml import column_mapping

REQUIRED_COLUMNS = [
    "order_id", "order_date", "customer_id", "customer_name", "region",
    "product_id", "product_name", "category", "quantity", "unit_price",
    "discount_pct", "revenue", "cost", "profit", "payment_method", "order_status",
]

NUMERIC_COLUMNS = ["quantity", "unit_price", "discount_pct", "revenue", "cost", "profit"]


class UnusableFileError(Exception):
    """Raised when an uploaded file has no recognizable date or monetary
    column, so it can't be treated as sales/order data at all."""
    pass


def profile_and_clean(df: pd.DataFrame):
    """Returns (cleaned_df, quality_report dict)."""
    report = {"rows_in": len(df)}

    # --- Auto-map real-world header names onto the canonical schema first,
    # so a file doesn't need to match the demo file's exact column names. ---
    df, mapping = column_mapping.map_columns(df)
    df = column_mapping.derive_missing_fields(df, mapping, report)

    # Ensure required columns exist (fill missing optional ones gracefully)
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    report["missing_columns"] = missing_cols
    for c in missing_cols:
        df[c] = np.nan

    # Drop anything that isn't part of the fixed schema (e.g. a leftover
    # free-text column like a review body, or any other field we didn't
    # map/derive). The 'orders' SQLite table is recreated from this
    # DataFrame's columns on every load, so an unrelated bulky text column
    # here would silently balloon the database and every API response that
    # touches per-row data -- for a 49k-row review dataset that was ~100MB+
    # of text with nothing to do with the dashboard.
    df = df[REQUIRED_COLUMNS].copy()

    # --- Type coercion ---
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    invalid_dates = int(df["order_date"].isna().sum())

    # A real date column existed but pandas couldn't parse ANY of its
    # values (unusual format, e.g. a non-standard locale). Rather than
    # dropping every single row, fall back to sequential synthetic dates
    # so the file still loads -- same trade-off as having no date column
    # at all, just flagged after the fact instead of before.
    if len(df) > 0 and invalid_dates == len(df) and mapping.get("order_date") is not None:
        synthetic = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(df), freq="D")
        df["order_date"] = synthetic
        invalid_dates = 0
        report.setdefault("assumptions", []).append(
            f"The date column ('{mapping['order_date']}') couldn't be parsed in any row — "
            "assumed sequential dates instead. Time-based figures aren't meaningful for this file."
        )

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    invalid_numeric = int(df[NUMERIC_COLUMNS].isna().sum().sum())

    # --- Missing values (before drop) ---
    missing_values = int(df.isna().sum().sum())

    # --- Duplicates ---
    duplicate_rows = int(df.duplicated().sum())
    df = df.drop_duplicates()

    # --- Drop rows with missing critical fields ---
    before = len(df)
    df = df.dropna(subset=["order_date", "customer_id", "revenue"])
    dropped_critical = before - len(df)

    if len(df) == 0:
        raise UnusableFileError(
            "After cleaning, no valid rows remained — every row was missing a "
            "usable date, customer ID, or revenue value. Please check that your "
            "date column contains real dates and your revenue/price column "
            "contains numbers, then try again."
        )

    # --- Fix invalid negative quantities / prices ---
    outliers = int(((df["quantity"] <= 0) | (df["unit_price"] < 0)).sum())
    df = df[(df["quantity"] > 0) & (df["unit_price"] >= 0)]

    if len(df) == 0:
        raise UnusableFileError(
            "After removing invalid rows (zero/negative quantity or price), "
            "no valid rows remained. Please check the quantity and price "
            "columns in your file and try again."
        )

    # --- Fill remaining gaps sensibly ---
    df["discount_pct"] = df["discount_pct"].fillna(0).clip(0, 0.9)
    df["cost"] = df["cost"].fillna(df["revenue"] * 0.7)
    df["profit"] = df["profit"].fillna(df["revenue"] - df["cost"])
    df["region"] = df["region"].fillna("Unknown")
    df["category"] = df["category"].fillna("Uncategorized")
    df["order_status"] = df["order_status"].fillna("Delivered")
    df["payment_method"] = df["payment_method"].fillna("Unknown")
    df["product_name"] = df["product_name"].fillna("General Item")
    df["product_id"] = df["product_id"].fillna("GEN-0001")
    df["customer_name"] = df["customer_name"].fillna(df["customer_id"].astype(str))

    # --- Statistical outlier flag (for reporting only, not removed) ---
    q1, q3 = df["revenue"].quantile([0.25, 0.75])
    iqr = q3 - q1
    stat_outliers = int(((df["revenue"] < q1 - 3 * iqr) | (df["revenue"] > q3 + 3 * iqr)).sum())

    df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")

    rows_out = len(df)
    total_checks = report["rows_in"] * len(REQUIRED_COLUMNS)
    issues = missing_values + duplicate_rows + invalid_dates + invalid_numeric + outliers
    quality_score = max(0.0, round(100 * (1 - issues / max(total_checks, 1)), 1))
    quality_score = min(quality_score, 100.0)

    report.update({
        "rows_out": rows_out,
        "missing_values": missing_values,
        "duplicate_records": duplicate_rows,
        "invalid_dates": invalid_dates,
        "invalid_numeric_values": invalid_numeric,
        "quantity_price_outliers_removed": outliers,
        "statistical_outliers_flagged": stat_outliers,
        "rows_dropped_missing_critical_fields": dropped_critical,
        "quality_score": quality_score,
    })

    return df.reset_index(drop=True), report
