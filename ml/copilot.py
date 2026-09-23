"""
AI Business Copilot.

A chat interface that answers management's questions using ONLY the
uploaded dataset's computed analytics (KPIs, regions, churn, root-cause,
opportunities) — never generic AI knowledge. Every question is answered
by first assembling a JSON "context bundle" of real numbers, then either
asking Groq to phrase an answer strictly from that bundle, or — if no
Groq key is configured — matching the question to a rule-based template
that reads directly from the same bundle. Either path is grounded.
"""

import json
from ml import groq_client


def build_context_bundle(kpis, regions, matrix, churn_summary, root_cause, opportunities, seasonality):
    return {
        "kpis": kpis,
        "regions": regions,
        "top_products": sorted(matrix, key=lambda x: -x["revenue"])[:5],
        "weak_products": [p for p in matrix if p["quadrant"] == "Weak"][:5],
        "churn_risk_summary": churn_summary,
        "root_cause_last_month": root_cause,
        "top_opportunities": opportunities[:5],
        "seasonality": seasonality,
    }


def _rule_based_answer(question: str, ctx: dict) -> str:
    q = question.lower()

    if "profit" in q and ("decrease" in q or "drop" in q or "fell" in q or "down" in q or "why" in q):
        rc = ctx["root_cause_last_month"]
        if not rc.get("available"):
            return rc.get("reason", "Not enough data yet to explain profit movement.")
        return (f"Profit moved {rc['profit_change_pct']}% between {rc['period']['previous']} and "
                f"{rc['period']['current']}. Primary driver: {rc['primary_driver']}.")

    if "at risk" in q or "at-risk" in q or "churn" in q:
        cs = ctx["churn_risk_summary"]
        high = cs.get("High Risk", 0)
        return (f"{high} customers are currently flagged High Risk, "
                f"{cs.get('Medium Risk', 0)} Medium Risk, and {cs.get('Low Risk', 0)} Low Risk. "
                f"Focus retention offers on the High Risk group first.")

    if "region" in q and ("focus" in q or "which" in q or "best" in q or "worst" in q):
        regions = sorted(ctx["regions"], key=lambda r: r["growth_pct"])
        worst = regions[0]
        best = regions[-1]
        return (f"{worst['region']} needs the most attention — growth is {worst['growth_pct']}% "
                f"with a {worst['margin_pct']}% margin. {best['region']} is performing best "
                f"at {best['growth_pct']}% growth.")

    if "opportunit" in q or "revenue" in q and "increase" in q:
        if ctx["top_opportunities"]:
            o = ctx["top_opportunities"][0]
            return f"Top opportunity: {o['opportunity']} — {o['reason']}. Recommended: {o['recommended_action']}."
        return "No major revenue opportunities are currently flagged."

    if "top product" in q or "best product" in q or "best selling" in q:
        if ctx["top_products"]:
            p = ctx["top_products"][0]
            return f"Your top product by revenue is '{p['product_name']}' with ₹{p['revenue']:,.0f} in revenue and ₹{p['profit']:,.0f} profit."

    # Generic fallback: summarize KPIs
    k = ctx["kpis"]
    return (f"Revenue is ₹{k['total_revenue']:,.0f} across {k['total_orders']} orders "
            f"at a {k['profit_margin_pct']}% margin, with {k['repeat_customer_rate_pct']}% repeat customers. "
            f"Ask me about profit changes, at-risk customers, regions, or revenue opportunities for more detail.")


def answer_question(question: str, ctx: dict) -> dict:
    system_prompt = (
        "You are an internal Business Intelligence copilot. You must answer the "
        "manager's question using ONLY the JSON data context provided — never use "
        "outside knowledge, never invent numbers not present in the context. If the "
        "context doesn't contain enough information to answer, say so plainly. Cite "
        "concrete figures from the context. Keep answers to 2-4 sentences, plain "
        "business language, no markdown headers."
    )
    user_prompt = f"DATA CONTEXT:\n{json.dumps(ctx, default=str)[:9000]}\n\nQUESTION: {question}"
    try:
        text = groq_client.ask_groq(system_prompt, user_prompt, max_tokens=350, temperature=0.2)
        return {"source": "groq-llm", "answer": text}
    except Exception as e:
        return {"source": "rule-based-fallback", "answer": _rule_based_answer(question, ctx), "note": str(e)}


SUGGESTED_QUESTIONS = [
    "Why did profit decrease this month?",
    "Which customers are at risk?",
    "Which region should I focus on?",
    "What are my top revenue opportunities?",
]
