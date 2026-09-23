"""
Root-Cause Analysis Engine.

Rather than just reporting "profit decreased 12%", decomposes the change
between the two most recent months into concrete contributing factors:
revenue movement, discount-rate movement, per-category margin movement,
and per-region sales movement — then names the single largest driver.
"""

import pandas as pd


def _last_two_months(df: pd.DataFrame):
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    d["month"] = d["order_date"].dt.to_period("M")
    months = sorted(d["month"].unique())
    if len(months) < 2:
        return None, None, d
    return months[-2], months[-1], d


def analyze_profit_change(df: pd.DataFrame) -> dict:
    prev_m, curr_m, d = _last_two_months(df)
    if prev_m is None:
        return {"available": False, "reason": "Not enough monthly history yet (need at least 2 months of data)."}

    prev = d[d["month"] == prev_m]
    curr = d[d["month"] == curr_m]

    def safe_pct(a, b):
        return round((b - a) / abs(a) * 100, 2) if a else 0

    prev_rev, curr_rev = prev["revenue"].sum(), curr["revenue"].sum()
    prev_profit, curr_profit = prev["profit"].sum(), curr["profit"].sum()
    prev_disc, curr_disc = prev["discount_pct"].mean(), curr["discount_pct"].mean()

    revenue_change_pct = safe_pct(prev_rev, curr_rev)
    profit_change_pct = safe_pct(prev_profit, curr_profit)
    discount_change_pp = round((curr_disc - prev_disc) * 100, 2)

    # Per-category margin movement
    def cat_margin(frame):
        g = frame.groupby("category").agg(revenue=("revenue", "sum"), profit=("profit", "sum"))
        g["margin_pct"] = (g["profit"] / g["revenue"] * 100).round(2)
        return g["margin_pct"]

    prev_cat_margin, curr_cat_margin = cat_margin(prev), cat_margin(curr)
    cat_moves = []
    for cat in set(prev_cat_margin.index) | set(curr_cat_margin.index):
        pm = prev_cat_margin.get(cat, 0)
        cm = curr_cat_margin.get(cat, 0)
        if abs(cm - pm) >= 1:
            cat_moves.append({"category": cat, "margin_change_pp": round(cm - pm, 2)})
    cat_moves.sort(key=lambda x: x["margin_change_pp"])

    # Per-region sales movement
    def region_rev(frame):
        return frame.groupby("region")["revenue"].sum()

    prev_region, curr_region = region_rev(prev), region_rev(curr)
    region_moves = []
    for reg in set(prev_region.index) | set(curr_region.index):
        pr, cr = prev_region.get(reg, 0), curr_region.get(reg, 0)
        pct = safe_pct(pr, cr)
        if abs(pct) >= 5:
            region_moves.append({"region": reg, "sales_change_pct": pct})
    region_moves.sort(key=lambda x: x["sales_change_pct"])

    # Build ranked list of contributing factors with an estimated ₹ impact
    factors = []
    factors.append({
        "factor": "Overall revenue movement", "detail": f"Revenue {'declined' if revenue_change_pct < 0 else 'grew'} {abs(revenue_change_pct)}%",
        "impact_rank": abs(revenue_change_pct),
    })
    if abs(discount_change_pp) >= 0.5:
        factors.append({
            "factor": "Discounting", "detail": f"Average discount {'increased' if discount_change_pp > 0 else 'decreased'} {abs(discount_change_pp)} percentage points",
            "impact_rank": abs(discount_change_pp) * 3,
        })
    for cm in cat_moves[:2]:
        factors.append({
            "factor": f"{cm['category']} margin", "detail": f"{cm['category']} margin {'fell' if cm['margin_change_pp'] < 0 else 'rose'} {abs(cm['margin_change_pp'])} points",
            "impact_rank": abs(cm["margin_change_pp"]) * 2,
        })
    for rm in region_moves[:2]:
        factors.append({
            "factor": f"{rm['region']} region sales", "detail": f"{rm['region']} sales {'dropped' if rm['sales_change_pct'] < 0 else 'grew'} {abs(rm['sales_change_pct'])}%",
            "impact_rank": abs(rm["sales_change_pct"]),
        })

    factors.sort(key=lambda x: -x["impact_rank"])
    primary_driver = factors[0]["detail"] if factors else "No significant single driver identified"

    return {
        "available": True,
        "period": {"previous": str(prev_m), "current": str(curr_m)},
        "profit_change_pct": profit_change_pct,
        "revenue_change_pct": revenue_change_pct,
        "discount_change_pp": discount_change_pp,
        "category_margin_moves": cat_moves,
        "region_sales_moves": region_moves,
        "factors": factors[:6],
        "primary_driver": primary_driver,
    }
