"""
What-If Business Simulator + Scenario Comparison.

Projects revenue/profit/margin impact of changing discount %, expected
order volume, marketing-driven demand lift, average price, and customer
retention rate — starting from the business's actual current KPIs so the
simulation is grounded in real data, not a generic model.
"""

import numpy as np


def _project(kpis, rfm_df, discount_delta_pct=0.0, orders_delta_pct=0.0,
             marketing_delta_pct=0.0, price_delta_pct=0.0, retention_delta_pct=0.0):
    """All *_delta_pct are percentage-point or percent changes vs. current."""
    base_revenue = kpis["total_revenue"]
    base_profit = kpis["total_profit"]
    base_orders = kpis["total_orders"]
    base_margin_pct = kpis["profit_margin_pct"]

    # Orders respond to marketing spend (elasticity ~0.6) and are set directly
    # via orders_delta_pct if provided.
    order_multiplier = (1 + orders_delta_pct / 100) * (1 + (marketing_delta_pct / 100) * 0.6)
    new_orders = base_orders * order_multiplier

    # Price and discount both move the effective average price per order.
    avg_price_multiplier = (1 + price_delta_pct / 100) * (1 - discount_delta_pct / 100 * 0.9)
    new_revenue = base_revenue * order_multiplier * avg_price_multiplier

    # Discount eats directly into margin (roughly 1:1 on the discounted slice);
    # retention improvements lift margin slightly via lower acquisition cost.
    margin_pp_change = (-discount_delta_pct * 0.9) + (retention_delta_pct * 0.12) + (price_delta_pct * 0.35)
    new_margin_pct = max(0.5, base_margin_pct + margin_pp_change)
    new_profit = new_revenue * (new_margin_pct / 100)

    # Marketing spend is a cost — subtract its absolute rupee value from profit.
    marketing_cost_estimate = base_revenue * 0.03 * (marketing_delta_pct / 100) if marketing_delta_pct else 0
    new_profit -= max(0, marketing_cost_estimate)

    customers_est = None
    if rfm_df is not None and len(rfm_df):
        base_customers = rfm_df["customer_id"].nunique()
        customers_est = round(base_customers * (1 + retention_delta_pct / 100 * 0.25 + orders_delta_pct / 100 * 0.1))

    return {
        "revenue": round(new_revenue, 2),
        "profit": round(new_profit, 2),
        "orders": round(new_orders),
        "margin_pct": round(new_profit / new_revenue * 100, 2) if new_revenue else 0,
        "customers": customers_est,
    }


def run_simulation(kpis, rfm_df, params: dict) -> dict:
    """params keys (all optional, default 0): discount_delta_pct, orders_delta_pct,
    marketing_delta_pct, price_delta_pct, retention_delta_pct"""
    baseline = {
        "revenue": kpis["total_revenue"], "profit": kpis["total_profit"],
        "orders": kpis["total_orders"], "margin_pct": kpis["profit_margin_pct"],
        "customers": rfm_df["customer_id"].nunique() if rfm_df is not None else None,
    }
    projected = _project(
        kpis, rfm_df,
        discount_delta_pct=float(params.get("discount_delta_pct", 0) or 0),
        orders_delta_pct=float(params.get("orders_delta_pct", 0) or 0),
        marketing_delta_pct=float(params.get("marketing_delta_pct", 0) or 0),
        price_delta_pct=float(params.get("price_delta_pct", 0) or 0),
        retention_delta_pct=float(params.get("retention_delta_pct", 0) or 0),
    )

    def delta(a, b):
        if not a:
            return 0
        return round((b - a) / abs(a) * 100, 2)

    impact = {
        "revenue_change": round(projected["revenue"] - baseline["revenue"], 2),
        "profit_change": round(projected["profit"] - baseline["profit"], 2),
        "margin_change_pp": round(projected["margin_pct"] - baseline["margin_pct"], 2),
        "revenue_change_pct": delta(baseline["revenue"], projected["revenue"]),
        "profit_change_pct": delta(baseline["profit"], projected["profit"]),
    }

    return {"baseline": baseline, "projected": projected, "impact": impact, "params": params}


def compare_scenarios(kpis, rfm_df, scenario_a: dict, scenario_b: dict) -> dict:
    a = run_simulation(kpis, rfm_df, scenario_a)
    b = run_simulation(kpis, rfm_df, scenario_b)
    return {
        "current": a["baseline"],
        "scenario_a": {"label": scenario_a.get("label", "Current Strategy"), "params": scenario_a, **a["projected"]},
        "scenario_b": {"label": scenario_b.get("label", "Proposed Strategy"), "params": scenario_b, **b["projected"]},
        "delta": {
            "revenue": round(b["projected"]["revenue"] - a["projected"]["revenue"], 2),
            "profit": round(b["projected"]["profit"] - a["projected"]["profit"], 2),
            "margin_pct": round(b["projected"]["margin_pct"] - a["projected"]["margin_pct"], 2),
            "customers": (b["projected"]["customers"] or 0) - (a["projected"]["customers"] or 0),
        },
    }
