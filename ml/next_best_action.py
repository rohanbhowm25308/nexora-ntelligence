"""
Next-Best-Action Engine — turns segmentation/risk/profitability signals
into one concrete recommended action per customer and per product.
"""

import pandas as pd


def customer_next_best_action(rfm_df: pd.DataFrame, churn_df: pd.DataFrame, clv_df: pd.DataFrame) -> pd.DataFrame:
    merged = rfm_df.merge(
        churn_df[["customer_id", "risk_level", "churn_probability"]], on="customer_id", how="left"
    ).merge(
        clv_df[["customer_id", "clv_estimate", "clv_tier"]], on="customer_id", how="left"
    )

    def action_for(row):
        seg, risk, clv_tier = row["segment"], row["risk_level"], row["clv_tier"]
        if seg == "VIP" and risk in ("Medium Risk", "High Risk"):
            return "Priority retention call + loyalty perk — high-value customer showing risk signals."
        if seg == "VIP":
            return "Offer an early-access or premium product bundle to deepen loyalty."
        if risk == "High Risk" and clv_tier in ("High CLV", "Medium CLV"):
            return "Send a personalized win-back offer before this valuable customer churns."
        if risk == "High Risk":
            return "Send a low-cost re-engagement email; do not over-invest given lower lifetime value."
        if seg in ("At Risk",):
            return "Send a personalized retention offer with a time-limited discount."
        if seg == "New":
            return "Send an onboarding series highlighting complementary products."
        if seg == "Potential Loyal":
            return "Nudge with a loyalty-program invite to increase purchase frequency."
        if seg == "Lost":
            return "Low-cost win-back campaign only; consider suppressing from paid marketing."
        return "Maintain standard engagement cadence — customer is healthy."

    merged["recommended_action"] = merged.apply(action_for, axis=1)
    cols = ["customer_id", "customer_name", "segment", "risk_level", "clv_estimate", "clv_tier",
            "recency", "frequency", "monetary", "recommended_action"]
    return merged[cols].round(2)


def product_next_best_action(matrix: list) -> list:
    out = []
    for p in matrix:
        quadrant = p["quadrant"]
        if quadrant == "Profit Leaders":
            action = "Protect and promote — increase visibility/inventory allocation."
        elif quadrant == "Stars":
            action = "Low sales but high margin — increase marketing spend and shelf placement."
        elif quadrant == "Revenue Drivers":
            action = "High revenue but low profit — review pricing or reduce discount depth."
        else:
            action = "Low sales and low margin — consider phasing out or bundling to clear stock."
        out.append({**p, "recommended_action": action})
    out.sort(key=lambda x: -x["revenue"])
    return out
