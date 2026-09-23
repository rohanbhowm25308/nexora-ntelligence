"""
Core rule-based analytics engine covering most of the "Data Science
add-on" features from the brief: KPI computation, product profitability
matrix, discount impact analysis, regional & seasonal intelligence,
anomaly detection, profit leakage, market-basket association, business
health scorecard, smart alerts, and recommendation generation.

Kept deliberately transparent (pandas/numpy + simple statistics) so every
number shown on the dashboard can be explained to a reviewer.
"""

import numpy as np
import pandas as pd
from itertools import combinations
from collections import Counter


def compute_kpis(df: pd.DataFrame) -> dict:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])

    total_revenue = float(d["revenue"].sum())
    total_profit = float(d["profit"].sum())
    total_orders = int(d["order_id"].nunique())
    total_customers = int(d["customer_id"].nunique())
    aov = round(total_revenue / total_orders, 2) if total_orders else 0
    margin = round(total_profit / total_revenue * 100, 2) if total_revenue else 0

    order_counts = d.groupby("customer_id")["order_id"].nunique()
    repeat_customers = int((order_counts > 1).sum())
    repeat_rate = round(repeat_customers / total_customers * 100, 2) if total_customers else 0
    revenue_per_customer = round(total_revenue / total_customers, 2) if total_customers else 0

    d["month"] = d["order_date"].dt.to_period("M")
    monthly_rev = d.groupby("month")["revenue"].sum()
    growth_pct = None
    if len(monthly_rev) >= 2:
        prev, curr = monthly_rev.iloc[-2], monthly_rev.iloc[-1]
        growth_pct = round((curr - prev) / prev * 100, 2) if prev else None

    return {
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "total_orders": total_orders,
        "aov": aov,
        "profit_margin_pct": margin,
        "total_customers": total_customers,
        "growth_pct": growth_pct,
        "repeat_customer_rate_pct": repeat_rate,
        "revenue_per_customer": revenue_per_customer,
        "monthly_trend": [
            {"month": str(m), "revenue": round(v, 2)} for m, v in monthly_rev.items()
        ],
    }


def product_profitability_matrix(df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"]
    g = d.groupby("product_name").agg(revenue=("revenue", "sum"), profit=("profit", "sum")).reset_index()
    rev_med, profit_med = g["revenue"].median(), g["profit"].median()

    def quadrant(row):
        high_sales = row["revenue"] >= rev_med
        high_profit = row["profit"] >= profit_med
        if high_sales and high_profit:
            return "Profit Leaders"
        if high_sales and not high_profit:
            return "Revenue Drivers"
        if not high_sales and high_profit:
            return "Stars"
        return "Weak"

    g["quadrant"] = g.apply(quadrant, axis=1)
    g = g.round(2)
    return g.to_dict(orient="records")


def discount_impact(df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"].copy()
    bins = [-0.01, 0.05, 0.15, 0.25, 0.4, 1.0]
    labels = ["0-5%", "5-15%", "15-25%", "25-40%", "40%+"]
    d["discount_band"] = pd.cut(d["discount_pct"], bins=bins, labels=labels)
    g = d.groupby("discount_band", observed=True).agg(
        orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
        profit=("profit", "sum"),
    ).reset_index()
    g["margin_pct"] = (g["profit"] / g["revenue"] * 100).round(2)
    g = g.round(2)
    return g.to_dict(orient="records")


def regional_intelligence(df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    g = d.groupby("region").agg(
        revenue=("revenue", "sum"), profit=("profit", "sum"),
        orders=("order_id", "nunique"), customers=("customer_id", "nunique"),
    ).reset_index()
    g["aov"] = (g["revenue"] / g["orders"]).round(2)
    g["margin_pct"] = (g["profit"] / g["revenue"] * 100).round(2)

    # growth: compare last 2 months per region
    d["month"] = d["order_date"].dt.to_period("M")
    monthly = d.groupby(["region", "month"])["revenue"].sum().reset_index()
    growth = {}
    for region, sub in monthly.groupby("region"):
        sub = sub.sort_values("month")
        if len(sub) >= 2 and sub["revenue"].iloc[-2]:
            growth[region] = round((sub["revenue"].iloc[-1] - sub["revenue"].iloc[-2]) / sub["revenue"].iloc[-2] * 100, 2)
        else:
            growth[region] = 0
    g["growth_pct"] = g["region"].map(growth)

    def flag(row):
        if row["margin_pct"] < 10 or row["growth_pct"] < -5:
            return "Needs Attention"
        return "Healthy"
    g["status"] = g.apply(flag, axis=1)
    g = g.round(2)
    return g.sort_values("revenue", ascending=False).to_dict(orient="records")


def region_drilldown(df: pd.DataFrame, region: str) -> dict:
    """Region -> Category -> Product -> Top customers, for a click-through drill-down."""
    d = df[(df["order_status"] != "Cancelled") & (df["region"] == region)]
    if d.empty:
        return {"region": region, "found": False}

    by_category = d.groupby("category").agg(
        revenue=("revenue", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
    ).reset_index().sort_values("revenue", ascending=False).round(2)

    by_product = d.groupby(["product_name", "category"]).agg(
        revenue=("revenue", "sum"), profit=("profit", "sum"), units=("quantity", "sum"),
    ).reset_index().sort_values("revenue", ascending=False).head(10).round(2)

    by_customer = d.groupby(["customer_id", "customer_name"]).agg(
        revenue=("revenue", "sum"), orders=("order_id", "nunique"),
    ).reset_index().sort_values("revenue", ascending=False).head(10).round(2)

    return {
        "region": region, "found": True,
        "categories": by_category.to_dict(orient="records"),
        "products": by_product.to_dict(orient="records"),
        "customers": by_customer.to_dict(orient="records"),
    }


def seasonal_intelligence(df: pd.DataFrame) -> dict:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["month_name"] = d["order_date"].dt.month_name()
    d["dow_name"] = d["order_date"].dt.day_name()

    monthly = d.groupby("month_name")["revenue"].sum().sort_values(ascending=False)
    dow = d.groupby("dow_name")["revenue"].sum().sort_values(ascending=False)
    cat_month = d.groupby(["category", "month_name"])["revenue"].sum().reset_index()
    top_cat_month = cat_month.sort_values("revenue", ascending=False).head(5)

    return {
        "high_demand_months": monthly.head(3).round(2).to_dict(),
        "low_demand_months": monthly.tail(3).round(2).to_dict(),
        "day_of_week_pattern": dow.round(2).to_dict(),
        "category_seasonality_highlights": top_cat_month.round(2).to_dict(orient="records"),
    }


def detect_anomalies(df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    daily = d.groupby("order_date").agg(
        revenue=("revenue", "sum"), orders=("order_id", "nunique"),
        discount=("discount_pct", "mean"), profit=("profit", "sum"),
    ).reset_index()

    anomalies = []
    for col, label in [("revenue", "Revenue"), ("orders", "Orders"), ("discount", "Discount"), ("profit", "Profit")]:
        mean, std = daily[col].mean(), daily[col].std()
        if std == 0 or np.isnan(std):
            continue
        z = (daily[col] - mean) / std
        flagged = daily[abs(z) > 2.5]
        for _, row in flagged.iterrows():
            direction = "Spike" if row[col] > mean else "Drop"
            severity = "Unusual" if abs((row[col]-mean)/std) < 3.5 else "Abnormal"
            anomalies.append({
                "date": row["order_date"].strftime("%Y-%m-%d"),
                "metric": label,
                "value": round(float(row[col]), 2),
                "type": f"{severity} {label} {direction}",
            })
    return sorted(anomalies, key=lambda x: x["date"], reverse=True)[:25]


def profit_leakage(df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"].copy()
    g = d.groupby(["product_name", "category"]).agg(
        revenue=("revenue", "sum"), profit=("profit", "sum"),
        avg_discount=("discount_pct", "mean"),
    ).reset_index()
    g["margin_pct"] = (g["profit"] / g["revenue"] * 100).round(2)
    leaks = g[(g["revenue"] >= g["revenue"].median()) & (g["avg_discount"] > 0.2) & (g["margin_pct"] < 10)]
    leaks = leaks.sort_values("revenue", ascending=False).round(2)
    return leaks.to_dict(orient="records")


def market_basket(df: pd.DataFrame, min_support=3, top_n=10) -> list:
    d = df[df["order_status"] != "Cancelled"]
    basket = d.groupby("order_id")["product_name"].apply(lambda x: sorted(set(x)))
    pair_counts = Counter()
    for items in basket:
        if len(items) > 1:
            for a, b in combinations(items, 2):
                pair_counts[(a, b)] += 1
    pairs = [
        {"product_a": a, "product_b": b, "times_bought_together": c}
        for (a, b), c in pair_counts.items() if c >= min_support
    ]
    pairs.sort(key=lambda x: -x["times_bought_together"])
    return pairs[:top_n]


def revenue_opportunities(df: pd.DataFrame) -> list:
    opportunities = []
    matrix = pd.DataFrame(product_profitability_matrix(df))
    if not matrix.empty:
        stars = matrix[matrix["quadrant"] == "Stars"].sort_values("profit", ascending=False).head(3)
        for _, r in stars.iterrows():
            opportunities.append({
                "opportunity": f"Promote '{r['product_name']}' more heavily",
                "potential_impact": "Medium-High",
                "reason": "High profit margin but currently low sales volume",
                "recommended_action": "Increase marketing spend / bundle with high-traffic products",
            })

    regions = pd.DataFrame(regional_intelligence(df))
    if not regions.empty:
        weak = regions[regions["status"] == "Needs Attention"]
        for _, r in weak.iterrows():
            opportunities.append({
                "opportunity": f"Improve performance in {r['region']} region",
                "potential_impact": "High",
                "reason": f"Margin {r['margin_pct']}% / growth {r['growth_pct']}% below healthy thresholds",
                "recommended_action": "Regional promotions, pricing review, or localized inventory planning",
            })

    baskets = market_basket(df, min_support=2, top_n=3)
    for b in baskets:
        opportunities.append({
            "opportunity": f"Bundle '{b['product_a']}' with '{b['product_b']}'",
            "potential_impact": "Medium",
            "reason": f"Purchased together {b['times_bought_together']} times",
            "recommended_action": "Create a bundle offer / cross-sell prompt at checkout",
        })

    return opportunities[:10]


def health_scorecard(kpis: dict, regions: list) -> list:
    scorecard = []
    growth = kpis.get("growth_pct") or 0
    scorecard.append({"kpi": "Revenue Growth", "value": f"{growth}%", "status": "Healthy" if growth >= 0 else "Attention"})
    scorecard.append({"kpi": "Profit Margin", "value": f"{kpis['profit_margin_pct']}%", "status": "Healthy" if kpis["profit_margin_pct"] >= 15 else "Attention"})
    scorecard.append({"kpi": "Customer Retention", "value": f"{kpis['repeat_customer_rate_pct']}%", "status": "Healthy" if kpis["repeat_customer_rate_pct"] >= 30 else "Attention"})
    attention_regions = sum(1 for r in regions if r["status"] == "Needs Attention")
    scorecard.append({"kpi": "Regional Growth", "value": f"{attention_regions} region(s) flagged", "status": "Healthy" if attention_regions == 0 else "Attention"})
    return scorecard


def smart_alerts(kpis: dict, anomalies: list, churn_df: pd.DataFrame, regions: list) -> list:
    alerts = []
    if kpis.get("growth_pct") is not None and kpis["growth_pct"] < -10:
        alerts.append({"icon": "\U0001F514", "message": f"Revenue dropped {abs(kpis['growth_pct'])}% vs last month"})
    for a in anomalies[:3]:
        alerts.append({"icon": "\U0001F514", "message": f"{a['type']} detected on {a['date']}"})
    high_risk_vip = churn_df[(churn_df["risk_level"] == "High Risk") & (churn_df["segment"].isin(["VIP", "Loyal"]))]
    if len(high_risk_vip):
        alerts.append({"icon": "\U0001F514", "message": f"{len(high_risk_vip)} high-value customer(s) becoming inactive"})
    for r in regions:
        if r["status"] == "Needs Attention":
            alerts.append({"icon": "\U0001F514", "message": f"{r['region']} region growth slowed to {r['growth_pct']}%"})
    return alerts[:8]


def generate_recommendations(churn_df: pd.DataFrame, matrix: list, regions: list) -> list:
    recs = []
    at_risk_count = int((churn_df["risk_level"] == "High Risk").sum())
    if at_risk_count:
        recs.append({
            "problem": f"{at_risk_count} customers at high churn risk",
            "recommendation": "Launch a targeted retention campaign (personalized discount / re-engagement email)",
        })
    weak_products = [m for m in matrix if m["quadrant"] == "Revenue Drivers"]
    if weak_products:
        top = sorted(weak_products, key=lambda x: -x["revenue"])[:2]
        for p in top:
            recs.append({
                "problem": f"'{p['product_name']}' has high revenue but low profit",
                "recommendation": "Review pricing or discount strategy for this product",
            })
    for r in regions:
        if r["status"] == "Needs Attention":
            recs.append({
                "problem": f"{r['region']} region underperforming (margin {r['margin_pct']}%)",
                "recommendation": "Investigate regional pricing, logistics costs, or launch local promotions",
            })
    return recs[:8]


# =====================================================================
# Data Detective — automated issue discovery with view/explain/fix
# =====================================================================
def data_detective(df: pd.DataFrame, quality_report: dict) -> list:
    """Turns the quality report + a few extra live checks into a list of
    discrete, explainable issues a reviewer can click through."""
    issues = []

    if quality_report.get("missing_values"):
        issues.append({
            "issue": f"{quality_report['missing_values']} missing values found",
            "severity": "Medium",
            "explain": "Some rows had blank fields (commonly revenue, dates, or IDs) that could break aggregations.",
            "fix": "Rows with missing critical fields (date, customer, revenue) were dropped; others were filled with sensible defaults.",
        })
    if quality_report.get("duplicate_records"):
        issues.append({
            "issue": f"{quality_report['duplicate_records']} duplicate records found",
            "severity": "Medium",
            "explain": "Identical rows can double-count revenue and inflate order volume.",
            "fix": "Exact duplicate rows were removed automatically before loading into the database.",
        })
    if quality_report.get("invalid_dates"):
        issues.append({
            "issue": f"{quality_report['invalid_dates']} invalid or unparseable dates",
            "severity": "High",
            "explain": "Rows with dates that couldn't be parsed would break monthly trends and forecasting.",
            "fix": "Rows with unparseable dates were excluded from time-based analysis.",
        })
    if quality_report.get("invalid_numeric_values"):
        issues.append({
            "issue": f"{quality_report['invalid_numeric_values']} invalid numeric values",
            "severity": "Medium",
            "explain": "Non-numeric or corrupted values in price/quantity/revenue fields were detected.",
            "fix": "Non-numeric values were coerced to blank and then filled with column-appropriate defaults.",
        })
    if quality_report.get("quantity_price_outliers_removed"):
        issues.append({
            "issue": f"{quality_report['quantity_price_outliers_removed']} rows with impossible quantity/price removed",
            "severity": "High",
            "explain": "Negative or zero quantities and negative prices are not valid transactions.",
            "fix": "These rows were removed prior to analysis.",
        })
    if quality_report.get("statistical_outliers_flagged"):
        issues.append({
            "issue": f"{quality_report['statistical_outliers_flagged']} statistical revenue outliers flagged",
            "severity": "Low",
            "explain": "These orders sit far outside the typical revenue range (>3× IQR) — could be bulk orders or data entry errors.",
            "fix": "Kept in the dataset but flagged for manual review; not removed automatically to avoid discarding real bulk orders.",
        })

    d = df[df["order_status"] != "Cancelled"]
    negative_rev = int((d["revenue"] < 0).sum())
    if negative_rev:
        issues.append({
            "issue": f"{negative_rev} orders with negative revenue",
            "severity": "High",
            "explain": "Negative revenue on a non-cancelled order usually indicates a refund miscoded as a sale.",
            "fix": "Flagged for review — not altered automatically since intent (refund vs. error) is ambiguous.",
        })

    high_discount = int((d["discount_pct"] > 0.6).sum())
    if high_discount:
        issues.append({
            "issue": f"{high_discount} orders with discount above 60%",
            "severity": "Low",
            "explain": "Unusually deep discounts can indicate promo abuse or a pricing error.",
            "fix": "Flagged for manual review in the Discount Impact Analyzer.",
        })

    score = quality_report.get("quality_score", 100)
    if not issues:
        issues.append({
            "issue": "No significant data quality issues detected",
            "severity": "None",
            "explain": "The dataset passed all automated checks.",
            "fix": "No action needed.",
        })

    return {"quality_score": score, "issues_found": len([i for i in issues if i["severity"] != "None"]), "issues": issues}


# =====================================================================
# Executive Command Center — single premium summary page
# =====================================================================
def business_health_score(kpis: dict, regions: list, churn_summary: dict) -> int:
    score = 100
    growth = kpis.get("growth_pct") or 0
    if growth < 0:
        score -= min(20, abs(growth))
    if kpis["profit_margin_pct"] < 15:
        score -= (15 - kpis["profit_margin_pct"])
    if kpis["repeat_customer_rate_pct"] < 30:
        score -= (30 - kpis["repeat_customer_rate_pct"]) * 0.3
    attention_regions = sum(1 for r in regions if r["status"] == "Needs Attention")
    score -= attention_regions * 4
    total_customers = sum(churn_summary.values()) or 1
    high_risk_share = churn_summary.get("High Risk", 0) / total_customers
    score -= high_risk_share * 30
    return int(max(0, min(100, round(score))))


def command_center(kpis, regions, churn_summary, matrix, opportunities, recommendations) -> dict:
    health = business_health_score(kpis, regions, churn_summary)

    top_issues = []
    if (kpis.get("growth_pct") or 0) < 0:
        top_issues.append(f"Revenue growth is negative ({kpis['growth_pct']}%)")
    weak = [m for m in matrix if m["quadrant"] == "Revenue Drivers"]
    if weak:
        top_issues.append(f"'{max(weak, key=lambda x: x['revenue'])['product_name']}' has high revenue but weak margin")
    for r in regions:
        if r["status"] == "Needs Attention":
            top_issues.append(f"{r['region']} region sales/margin needs attention")
    high_risk = churn_summary.get("High Risk", 0)
    if high_risk:
        top_issues.append(f"{high_risk} customers at high churn risk")

    top_opps = [o["opportunity"] for o in opportunities[:3]]

    return {
        "health_score": health,
        "health_status": "Excellent" if health >= 80 else "Good" if health >= 65 else "Attention" if health >= 45 else "Critical",
        "kpis": kpis,
        "total_customers": sum(churn_summary.values()),
        "at_risk_customers": high_risk,
        "top_issues": top_issues[:3] if top_issues else ["No major issues detected — business is healthy"],
        "top_opportunities": top_opps if top_opps else ["No major opportunities flagged right now"],
    }


# =====================================================================
# Enhanced Revenue Opportunity Scanner (with rupee-value estimates)
# =====================================================================
def revenue_opportunity_scan(df: pd.DataFrame, rfm_df: pd.DataFrame, churn_df: pd.DataFrame) -> list:
    d = df[df["order_status"] != "Cancelled"]
    scans = []

    # High-value customers gone quiet
    merged = rfm_df.merge(churn_df[["customer_id", "risk_level"]], on="customer_id", how="left")
    quiet_high_value = merged[(merged["recency"] > 60) & (merged["monetary"] > merged["monetary"].median())]
    if len(quiet_high_value):
        potential = round(quiet_high_value["monetary"].median() * len(quiet_high_value) * 0.3, 2)
        scans.append({
            "opportunity": "Retention win-back campaign",
            "potential_impact": f"₹{potential:,.0f}",
            "reason": f"{len(quiet_high_value)} high-value customers have not purchased in the last 60 days.",
            "recommended_action": "Launch a targeted win-back offer to this segment.",
        })

    # Cross-sell from market basket
    baskets = market_basket(df, min_support=2, top_n=3)
    for b in baskets:
        scans.append({
            "opportunity": f"Bundle '{b['product_a']}' with '{b['product_b']}'",
            "potential_impact": "Medium",
            "reason": f"Purchased together {b['times_bought_together']} times already.",
            "recommended_action": "Create a bundle offer or checkout cross-sell prompt.",
        })

    # Region expansion
    regions = regional_intelligence(df)
    low_growth = [r for r in regions if r["growth_pct"] < 0]
    for r in low_growth[:2]:
        scans.append({
            "opportunity": f"Expand presence in {r['region']}",
            "potential_impact": f"₹{abs(r['revenue'] * 0.1):,.0f} (10% recovery)",
            "reason": f"{r['region']} growth is {r['growth_pct']}%, underperforming other regions.",
            "recommended_action": "Local promotions, pricing review, or expanded product availability.",
        })

    # Pricing optimization on high-revenue/low-profit products
    matrix = product_profitability_matrix(df)
    revenue_drivers = sorted([m for m in matrix if m["quadrant"] == "Revenue Drivers"], key=lambda x: -x["revenue"])
    for p in revenue_drivers[:2]:
        scans.append({
            "opportunity": f"Pricing optimization: {p['product_name']}",
            "potential_impact": f"₹{p['revenue'] * 0.05:,.0f} (5% margin recovery)",
            "reason": "High revenue but disproportionately low profit — likely over-discounted.",
            "recommended_action": "Review discount depth and floor pricing for this product.",
        })

    return scans[:8]
