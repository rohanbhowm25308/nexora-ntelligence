"""
RFM Segmentation, Customer Lifetime Value, and Behavioral Profiling.
"""

import pandas as pd
import numpy as np


SEGMENT_EMOJI = {
    "VIP": "\U0001F48E",
    "Loyal": "\u2764\uFE0F",
    "Potential Loyal": "\U0001F331",
    "New": "\U0001F195",
    "At Risk": "\u26A0\uFE0F",
    "Lost": "\U0001F534",
}


def compute_rfm(df: pd.DataFrame, reference_date=None) -> pd.DataFrame:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    if reference_date is None:
        reference_date = d["order_date"].max() + pd.Timedelta(days=1)

    agg = d.groupby(["customer_id", "customer_name"]).agg(
        last_purchase=("order_date", "max"),
        first_purchase=("order_date", "min"),
        frequency=("order_id", "nunique"),
        monetary=("revenue", "sum"),
        avg_order_value=("revenue", "mean"),
        total_profit=("profit", "sum"),
    ).reset_index()

    agg["recency"] = (reference_date - agg["last_purchase"]).dt.days

    # Score 1-5 (5 = best) using quantiles, robust to ties
    def score(series, ascending):
        try:
            ranks = series.rank(method="first", ascending=ascending)
            return pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5]).astype(int)
        except ValueError:
            return pd.Series([3] * len(series), index=series.index)

    agg["R"] = score(agg["recency"], ascending=False)   # low recency (recent) -> high score
    agg["F"] = score(agg["frequency"], ascending=True)
    agg["M"] = score(agg["monetary"], ascending=True)
    agg["rfm_score"] = agg["R"].astype(str) + agg["F"].astype(str) + agg["M"].astype(str)
    agg["rfm_total"] = agg[["R", "F", "M"]].sum(axis=1)

    def segment(row):
        r, f, m = row["R"], row["F"], row["M"]
        if r >= 4 and f >= 4 and m >= 4:
            return "VIP"
        if r >= 3 and f >= 4:
            return "Loyal"
        if r >= 4 and f <= 2:
            return "New"
        if r >= 3 and f >= 2 and m >= 3:
            return "Potential Loyal"
        if r <= 2 and f >= 3:
            return "At Risk"
        if r <= 2 and f <= 2:
            return "Lost"
        return "Potential Loyal"

    agg["segment"] = agg.apply(segment, axis=1)
    agg["segment_label"] = agg["segment"].map(lambda s: f"{SEGMENT_EMOJI.get(s,'')} {s}")

    # Behavioral profile tags (feature 18)
    disc = d.groupby("customer_id")["discount_pct"].mean()
    agg = agg.merge(disc.rename("avg_discount"), on="customer_id", how="left")

    def behavior(row):
        if row["avg_discount"] > 0.25:
            return "Discount Sensitive Buyer"
        if row["frequency"] >= 8 and row["monetary"] > agg["monetary"].median() * 1.5:
            return "High-Value Frequent Buyer"
        if row["recency"] > 180:
            return "Inactive Customer"
        if row["frequency"] <= 2:
            return "Occasional Buyer"
        return "Category Specialist"

    agg["behavior_profile"] = agg.apply(behavior, axis=1)

    return agg


def compute_clv(rfm_df: pd.DataFrame, months_horizon: int = 12) -> pd.DataFrame:
    """Simple, explainable CLV estimate:
    CLV = avg_order_value * purchase_frequency_per_month * margin_rate * horizon_months
    """
    df = rfm_df.copy()
    tenure_days = (pd.Timestamp.now() - df["first_purchase"]).dt.days.clip(lower=30)
    monthly_freq = df["frequency"] / (tenure_days / 30)
    margin_rate = (df["total_profit"] / df["monetary"].replace(0, np.nan)).fillna(0.15).clip(0, 0.8)
    df["clv_estimate"] = (df["avg_order_value"] * monthly_freq * (1 + margin_rate) * months_horizon).round(2)

    q1, q2 = df["clv_estimate"].quantile([0.4, 0.8])
    df["clv_tier"] = np.select(
        [df["clv_estimate"] >= q2, df["clv_estimate"] >= q1],
        ["High CLV", "Medium CLV"], default="Low CLV"
    )
    return df


def cohort_retention(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["order_month"] = d["order_date"].dt.to_period("M")
    first_month = d.groupby("customer_id")["order_month"].min().rename("cohort_month")
    d = d.merge(first_month, on="customer_id")
    d["period_number"] = (d["order_month"] - d["cohort_month"]).apply(lambda x: x.n)

    cohort_data = d.groupby(["cohort_month", "period_number"])["customer_id"].nunique().reset_index()
    cohort_pivot = cohort_data.pivot(index="cohort_month", columns="period_number", values="customer_id")
    cohort_size = cohort_pivot.iloc[:, 0]
    retention = cohort_pivot.divide(cohort_size, axis=0).round(3) * 100
    retention.index = retention.index.astype(str)
    return retention.fillna(0).round(1)
