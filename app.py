"""
Business Intelligence & Sales Analytics System — Flask Backend
================================================================
Ties together: data upload & cleaning, SQLite storage, SQL analytics,
RFM segmentation, CLV, churn/risk ML model, sales forecasting, rule-based
+ Groq-LLM business insights, recommendations, and report generation.

Run:
    pip install -r requirements.txt
    python data/generate_data.py      # (optional) create a sample dataset
    python app.py
"""

import os
import io
import json
import threading
from datetime import datetime

import pandas as pd
from flask import Flask, request, jsonify, render_template, send_file
from dotenv import load_dotenv

from database import db
from ml.data_quality import UnusableFileError
from ml import data_quality, rfm as rfm_mod, churn_model, forecast as forecast_mod, insights, groq_client
from ml import simulator, root_cause, next_best_action, forecast_monitor, copilot

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload cap


@app.errorhandler(413)
def handle_too_large(e):
    # Flask's default 413 response is HTML, which breaks the frontend's
    # `res.json()` parsing and surfaces as a confusing "unexpected response"
    # error. Always return JSON from API routes so the upload UI can show
    # a clear, actionable message instead.
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"error": f"This file is too large (limit: {limit_mb} MB). "
                              f"Please upload a smaller file or split it into parts."}), 413


@app.after_request
def add_no_cache_headers(response):
    """Every /api/ response must always reflect the current in-memory
    dataset. Without this, browsers can silently serve a stale cached
    response for a GET request (e.g. /api/regions) even after the user
    has uploaded a brand new CSV, making the dashboard look "stuck" on
    the old data until a hard refresh."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.errorhandler(500)
def handle_internal_error(e):
    app.logger.exception("Unhandled server error")
    return jsonify({"error": "Something went wrong processing that request. Please try again."}), 500


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEFAULT_CSV = os.path.join(DATA_DIR, "sales_data.csv")

# In-memory cache so we don't recompute every model on every request.
_CACHE = {"df": None, "rfm": None, "clv": None, "churn_model": None,
          "churn_metrics": None, "churn_scores": None, "quality_report": None,
          "is_demo": True, "source_filename": None,
          "goals": {"revenue_target": 0, "profit_target": 0, "orders_target": 0}}


# ----------------------------------------------------------------------
# Data loading / pipeline
# ----------------------------------------------------------------------
def load_and_process(csv_path: str, is_demo: bool = False, filename: str = None):
    raw = pd.read_csv(csv_path)
    cleaned, quality_report = data_quality.profile_and_clean(raw)
    db.load_dataframe(cleaned)

    rfm_df = rfm_mod.compute_rfm(cleaned)
    clv_df = rfm_mod.compute_clv(rfm_df)
    model, metrics = churn_model.train_churn_model(rfm_df)
    churn_scores = churn_model.score_customers(rfm_df, model)

    _CACHE.update({
        "df": cleaned, "rfm": rfm_df, "clv": clv_df,
        "churn_model": model, "churn_metrics": metrics,
        "churn_scores": churn_scores, "quality_report": quality_report,
        "is_demo": is_demo, "source_filename": filename,
    })
    return quality_report


_LOAD_LOCK = threading.Lock()


def ensure_loaded():
    if _CACHE["df"] is None:
        with _LOAD_LOCK:
            # Re-check after acquiring the lock: another thread may have
            # already finished loading while we were waiting for it.
            if _CACHE["df"] is None:
                if not os.path.exists(DEFAULT_CSV):
                    import subprocess
                    subprocess.run(["python", os.path.join(DATA_DIR, "generate_data.py")],
                                    cwd=os.path.dirname(__file__), check=True)
                load_and_process(DEFAULT_CSV, is_demo=True, filename="Demo dataset (auto-generated)")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/data-status")
def api_data_status():
    ensure_loaded()
    return jsonify({
        "is_demo": _CACHE["is_demo"],
        "source_filename": _CACHE["source_filename"],
        "rows": len(_CACHE["df"]) if _CACHE["df"] is not None else 0,
    })


# ----------------------------------------------------------------------
# Upload -> Analyze -> Report pipeline
# ----------------------------------------------------------------------
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# The dashboard only ever displays 50-60 rows per table (see app.js), but
# for a file with no real repeat customers (e.g. one row = one customer),
# these endpoints used to ship every single customer -- 80-100+ MB of JSON
# for a ~285k-row file, which is enough to hang or crash a browser tab. Cap
# the per-record payload generously (still far more than the UI shows) while
# keeping aggregate summaries computed from the full dataset.
MAX_CUSTOMER_RECORDS = 1000


@app.route("/api/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file selected. Please choose a CSV or Excel file."}), 400

    from werkzeug.utils import secure_filename
    safe_name = secure_filename(file.filename) or "upload"
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type '{ext}'. Please upload a .csv, .xlsx, or .xls file."}), 400

    path = os.path.join(DATA_DIR, "uploaded_" + safe_name)
    try:
        file.save(path)

        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)
            csv_path = path.rsplit(".", 1)[0] + ".csv"
            df.to_csv(csv_path, index=False)
            path = csv_path
        else:
            # Quick sanity check so a malformed/empty CSV fails fast with a
            # clear message instead of hanging deep inside the ML pipeline.
            try:
                probe = pd.read_csv(path, nrows=5)
            except Exception:
                return jsonify({"error": "This file doesn't look like a valid CSV. Please check the format and try again."}), 400
            if probe.empty:
                return jsonify({"error": "The uploaded file has no data rows."}), 400

        with _LOAD_LOCK:
            report = load_and_process(path, is_demo=False, filename=file.filename)
        return jsonify({"status": "success", "quality_report": report})
    except pd.errors.EmptyDataError:
        return jsonify({"error": "The uploaded file is empty."}), 400
    except UnusableFileError as e:
        # File parsed fine but doesn't contain usable sales/order data
        # (e.g. no date column, no revenue/price column). Don't fall
        # through to the ML pipeline with empty/garbage data — tell the
        # user exactly what's missing instead.
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Upload processing failed")
        return jsonify({"error": f"Could not process this file: {e}"}), 500


@app.route("/api/load-demo", methods=["POST"])
def api_load_demo():
    try:
        if not os.path.exists(DEFAULT_CSV):
            import subprocess
            subprocess.run(["python", os.path.join(DATA_DIR, "generate_data.py")],
                            cwd=os.path.dirname(__file__), check=True)
        with _LOAD_LOCK:
            report = load_and_process(DEFAULT_CSV, is_demo=True, filename="Demo dataset (auto-generated)")
        return jsonify({"status": "success", "quality_report": report})
    except Exception as e:
        app.logger.exception("Demo load failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/data-quality")
def api_data_quality():
    ensure_loaded()
    return jsonify(_CACHE["quality_report"])


# ----------------------------------------------------------------------
# KPIs / Executive Dashboard
# ----------------------------------------------------------------------
@app.route("/api/kpis")
def api_kpis():
    ensure_loaded()
    return jsonify(insights.compute_kpis(_CACHE["df"]))


@app.route("/api/sql/<query_name>")
def api_sql(query_name):
    ensure_loaded()
    queries = {
        "monthly_trend": """SELECT strftime('%Y-%m', order_date) AS month,
                             ROUND(SUM(revenue),2) AS revenue, ROUND(SUM(profit),2) AS profit,
                             COUNT(DISTINCT order_id) AS orders
                             FROM orders WHERE order_status != 'Cancelled'
                             GROUP BY month ORDER BY month""",
        "top_products": """SELECT product_name, category, ROUND(SUM(revenue),2) AS revenue,
                            ROUND(SUM(profit),2) AS profit, SUM(quantity) AS units_sold
                            FROM orders WHERE order_status != 'Cancelled'
                            GROUP BY product_name, category ORDER BY revenue DESC LIMIT 10""",
        "top_customers": """SELECT customer_id, customer_name, ROUND(SUM(revenue),2) AS total_spent,
                             COUNT(DISTINCT order_id) AS total_orders, MAX(order_date) AS last_purchase
                             FROM orders WHERE order_status != 'Cancelled'
                             GROUP BY customer_id, customer_name ORDER BY total_spent DESC LIMIT 10""",
        "category_performance": """SELECT category, ROUND(SUM(revenue),2) AS revenue,
                             ROUND(SUM(profit),2) AS profit, SUM(quantity) AS units_sold
                             FROM orders WHERE order_status != 'Cancelled'
                             GROUP BY category ORDER BY revenue DESC""",
    }
    if query_name not in queries:
        return jsonify({"error": "Unknown query"}), 404
    result = db.run_query(queries[query_name])
    return jsonify(result.to_dict(orient="records"))


# ----------------------------------------------------------------------
# Segmentation / CLV / Customer 360 / Behavior
# ----------------------------------------------------------------------
@app.route("/api/rfm")
def api_rfm():
    ensure_loaded()
    df = _CACHE["rfm"]
    summary = df.groupby("segment").agg(
        customers=("customer_id", "count"), revenue=("monetary", "sum"),
    ).reset_index()
    summary["revenue_share_pct"] = (summary["revenue"] / summary["revenue"].sum() * 100).round(2)
    records = df[["customer_id", "customer_name", "recency", "frequency", "monetary",
                  "rfm_score", "segment", "segment_label", "behavior_profile"]].round(2)
    records = records.sort_values("monetary", ascending=False).head(MAX_CUSTOMER_RECORDS)
    return jsonify({
        "segment_summary": summary.round(2).to_dict(orient="records"),
        "customers": records.to_dict(orient="records"),
        "customers_truncated": len(df) > MAX_CUSTOMER_RECORDS,
        "total_customers": len(df),
    })


@app.route("/api/clv")
def api_clv():
    ensure_loaded()
    df = _CACHE["clv"]
    tier_summary = df.groupby("clv_tier").agg(
        customers=("customer_id", "count"), avg_clv=("clv_estimate", "mean")
    ).round(2).reset_index()
    cols = ["customer_id", "customer_name", "clv_estimate", "clv_tier", "segment", "behavior_profile"]
    records = df[cols].round(2).sort_values("clv_estimate", ascending=False).head(MAX_CUSTOMER_RECORDS)
    return jsonify({
        "tier_summary": tier_summary.to_dict(orient="records"),
        "customers": records.to_dict(orient="records"),
        "customers_truncated": len(df) > MAX_CUSTOMER_RECORDS,
        "total_customers": len(df),
    })


@app.route("/api/customer/<customer_id>")
def api_customer_360(customer_id):
    ensure_loaded()
    df = _CACHE["df"]
    rfm_df = _CACHE["rfm"]
    churn_df = _CACHE["churn_scores"]
    clv_df = _CACHE["clv"]

    cust_orders = df[df["customer_id"] == customer_id]
    if cust_orders.empty:
        return jsonify({"error": "Customer not found"}), 404

    rfm_row = rfm_df[rfm_df["customer_id"] == customer_id].iloc[0]
    risk_row = churn_df[churn_df["customer_id"] == customer_id].iloc[0]
    clv_row = clv_df[clv_df["customer_id"] == customer_id].iloc[0]

    fav_category = cust_orders.groupby("category")["revenue"].sum().idxmax()
    fav_product = cust_orders.groupby("product_name")["revenue"].sum().idxmax()

    timeline = cust_orders[["order_date", "product_name", "revenue", "order_status"]] \
        .sort_values("order_date").round(2).to_dict(orient="records")

    return jsonify({
        "customer_id": customer_id,
        "customer_name": rfm_row["customer_name"],
        "total_orders": int(rfm_row["frequency"]),
        "total_spending": round(float(rfm_row["monetary"]), 2),
        "avg_order_value": round(float(rfm_row["avg_order_value"]), 2),
        "last_purchase": str(rfm_row["last_purchase"].date()),
        "first_purchase": str(rfm_row["first_purchase"].date()),
        "favorite_category": fav_category,
        "favorite_product": fav_product,
        "rfm_score": rfm_row["rfm_score"],
        "segment": rfm_row["segment_label"],
        "behavior_profile": rfm_row["behavior_profile"],
        "risk_level": risk_row["risk_level"],
        "churn_probability": float(risk_row["churn_probability"]),
        "risk_factors": risk_row["risk_factors"],
        "clv_estimate": float(clv_row["clv_estimate"]),
        "clv_tier": clv_row["clv_tier"],
        "purchase_timeline": timeline,
    })


@app.route("/api/cohorts")
def api_cohorts():
    ensure_loaded()
    retention = rfm_mod.cohort_retention(_CACHE["df"])
    return jsonify(json.loads(retention.reset_index().to_json(orient="records")))


# ----------------------------------------------------------------------
# Churn / Risk
# ----------------------------------------------------------------------
@app.route("/api/churn")
def api_churn():
    ensure_loaded()
    df = _CACHE["churn_scores"]
    summary = df["risk_level"].value_counts().to_dict()
    records = df.round(3).sort_values("churn_probability", ascending=False).head(MAX_CUSTOMER_RECORDS)
    return jsonify({
        "model_metrics": _CACHE["churn_metrics"],
        "risk_summary": summary,
        "customers": records.to_dict(orient="records"),
        "customers_truncated": len(df) > MAX_CUSTOMER_RECORDS,
        "total_customers": len(df),
    })


# ----------------------------------------------------------------------
# Forecasting
# ----------------------------------------------------------------------
@app.route("/api/forecast")
def api_forecast():
    ensure_loaded()
    return jsonify(forecast_mod.forecast_sales(_CACHE["df"]))


# ----------------------------------------------------------------------
# Advanced analytics: profitability matrix, discounts, regions, season,
# anomalies, profit leakage, market basket, opportunities, health, alerts
# ----------------------------------------------------------------------
@app.route("/api/product-matrix")
def api_product_matrix():
    ensure_loaded()
    return jsonify(insights.product_profitability_matrix(_CACHE["df"]))


@app.route("/api/discount-impact")
def api_discount_impact():
    ensure_loaded()
    return jsonify(insights.discount_impact(_CACHE["df"]))


@app.route("/api/regions")
def api_regions():
    ensure_loaded()
    return jsonify(insights.regional_intelligence(_CACHE["df"]))


@app.route("/api/seasonality")
def api_seasonality():
    ensure_loaded()
    return jsonify(insights.seasonal_intelligence(_CACHE["df"]))


@app.route("/api/anomalies")
def api_anomalies():
    ensure_loaded()
    return jsonify(insights.detect_anomalies(_CACHE["df"]))


@app.route("/api/profit-leakage")
def api_profit_leakage():
    ensure_loaded()
    return jsonify(insights.profit_leakage(_CACHE["df"]))


@app.route("/api/market-basket")
def api_market_basket():
    ensure_loaded()
    return jsonify(insights.market_basket(_CACHE["df"]))


@app.route("/api/opportunities")
def api_opportunities():
    ensure_loaded()
    return jsonify(insights.revenue_opportunities(_CACHE["df"]))


@app.route("/api/health-scorecard")
def api_health_scorecard():
    ensure_loaded()
    kpis = insights.compute_kpis(_CACHE["df"])
    regions = insights.regional_intelligence(_CACHE["df"])
    return jsonify(insights.health_scorecard(kpis, regions))


@app.route("/api/alerts")
def api_alerts():
    ensure_loaded()
    kpis = insights.compute_kpis(_CACHE["df"])
    anomalies = insights.detect_anomalies(_CACHE["df"])
    regions = insights.regional_intelligence(_CACHE["df"])
    return jsonify(insights.smart_alerts(kpis, anomalies, _CACHE["churn_scores"], regions))


@app.route("/api/recommendations")
def api_recommendations():
    ensure_loaded()
    matrix = insights.product_profitability_matrix(_CACHE["df"])
    regions = insights.regional_intelligence(_CACHE["df"])
    return jsonify(insights.generate_recommendations(_CACHE["churn_scores"], matrix, regions))


# ----------------------------------------------------------------------
# KPI Goal Tracking (feature #20) — kept simple, in-memory per session
# ----------------------------------------------------------------------
@app.route("/api/goals", methods=["GET", "POST"])
def api_goals():
    ensure_loaded()
    if request.method == "POST":
        body = request.get_json(force=True)
        _CACHE["goals"].update({k: float(v) for k, v in body.items() if k in _CACHE["goals"]})
    kpis = insights.compute_kpis(_CACHE["df"])
    goals = _CACHE["goals"]

    def track(actual, target):
        target = target or 0
        pct = round(actual / target * 100, 1) if target else 0
        return {"actual": round(actual, 2), "target": target, "achievement_pct": pct,
                "gap": round(target - actual, 2)}

    return jsonify({
        "revenue": track(kpis["total_revenue"], goals["revenue_target"]),
        "profit": track(kpis["total_profit"], goals["profit_target"]),
        "orders": track(kpis["total_orders"], goals["orders_target"]),
    })


# ----------------------------------------------------------------------
# AI-Powered Business Insights (Groq) — with rule-based fallback
# ----------------------------------------------------------------------
@app.route("/api/ai-insights")
def api_ai_insights():
    ensure_loaded()
    kpis = insights.compute_kpis(_CACHE["df"])
    regions = insights.regional_intelligence(_CACHE["df"])
    top_products = insights.product_profitability_matrix(_CACHE["df"])
    anomalies = insights.detect_anomalies(_CACHE["df"])
    try:
        text = groq_client.generate_business_insights(kpis, regions, top_products, anomalies)
        return jsonify({"source": "groq-llm", "insights": text})
    except Exception as e:
        fallback = (
            f"Revenue reached ₹{kpis['total_revenue']:,.0f} across {kpis['total_orders']} orders "
            f"at a {kpis['profit_margin_pct']}% profit margin. "
            f"Repeat customer rate stands at {kpis['repeat_customer_rate_pct']}%. "
            f"Top region: {regions[0]['region'] if regions else 'N/A'}."
        )
        return jsonify({"source": "rule-based-fallback", "insights": fallback, "note": str(e)})


# ----------------------------------------------------------------------
# One-Click Executive Report
# ----------------------------------------------------------------------
@app.route("/api/report")
def api_report():
    ensure_loaded()
    df = _CACHE["df"]
    kpis = insights.compute_kpis(df)
    regions = insights.regional_intelligence(df)
    matrix = insights.product_profitability_matrix(df)
    churn = _CACHE["churn_scores"]
    forecast_data = forecast_mod.forecast_sales(df)
    anomalies = insights.detect_anomalies(df)
    recs = insights.generate_recommendations(churn, matrix, regions)
    rfm_summary = _CACHE["rfm"].groupby("segment")["customer_id"].count().to_dict()

    context = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kpis": kpis, "regions": regions, "rfm_summary": rfm_summary,
        "risk_summary": churn["risk_level"].value_counts().to_dict(),
        "forecast_next_30_days": forecast_data["forecast"]["next_30_days"],
        "anomalies": anomalies[:5], "recommendations": recs,
    }
    try:
        narrative = groq_client.generate_executive_report_narrative(context)
    except Exception:
        narrative = None

    return render_template("report.html", ctx=context, narrative=narrative,
                            top_products=sorted(matrix, key=lambda x: -x["revenue"])[:5])


@app.route("/api/report/download")
def api_report_download():
    html = api_report()
    buf = io.BytesIO(html.encode("utf-8") if isinstance(html, str) else html.get_data())
    buf.seek(0)
    return send_file(buf, mimetype="text/html", as_attachment=True,
                      download_name=f"executive_report_{datetime.now().strftime('%Y%m%d')}.html")


@app.route("/api/data/download")
def api_data_download():
    ensure_loaded()
    buf = io.StringIO()
    _CACHE["df"].to_csv(buf, index=False)
    mem = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                      download_name="cleaned_sales_data.csv")


# ----------------------------------------------------------------------
# 1. AI Business Copilot
# ----------------------------------------------------------------------
@app.route("/api/copilot", methods=["POST"])
def api_copilot():
    ensure_loaded()
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Question is required"}), 400

    df = _CACHE["df"]
    kpis = insights.compute_kpis(df)
    regions = insights.regional_intelligence(df)
    matrix = insights.product_profitability_matrix(df)
    churn_summary = _CACHE["churn_scores"]["risk_level"].value_counts().to_dict()
    rc = root_cause.analyze_profit_change(df)
    opps = insights.revenue_opportunity_scan(df, _CACHE["rfm"], _CACHE["churn_scores"])
    season = insights.seasonal_intelligence(df)

    ctx = copilot.build_context_bundle(kpis, regions, matrix, churn_summary, rc, opps, season)
    result = copilot.answer_question(question, ctx)
    return jsonify(result)


@app.route("/api/copilot/suggestions")
def api_copilot_suggestions():
    return jsonify(copilot.SUGGESTED_QUESTIONS)


# ----------------------------------------------------------------------
# 2 & 11. What-If Business Simulator + Scenario Comparison
# ----------------------------------------------------------------------
@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    ensure_loaded()
    params = request.get_json(force=True) or {}
    kpis = insights.compute_kpis(_CACHE["df"])
    result = simulator.run_simulation(kpis, _CACHE["rfm"], params)
    return jsonify(result)


@app.route("/api/scenario-compare", methods=["POST"])
def api_scenario_compare():
    ensure_loaded()
    body = request.get_json(force=True) or {}
    scenario_a = body.get("scenario_a", {})
    scenario_b = body.get("scenario_b", {})
    kpis = insights.compute_kpis(_CACHE["df"])
    result = simulator.compare_scenarios(kpis, _CACHE["rfm"], scenario_a, scenario_b)
    return jsonify(result)


# ----------------------------------------------------------------------
# 3. Root-Cause Analysis Engine
# ----------------------------------------------------------------------
@app.route("/api/root-cause")
def api_root_cause():
    ensure_loaded()
    return jsonify(root_cause.analyze_profit_change(_CACHE["df"]))


# ----------------------------------------------------------------------
# 4. Revenue Opportunity Scanner (enhanced, with ₹ impact estimates)
# ----------------------------------------------------------------------
@app.route("/api/revenue-scan")
def api_revenue_scan():
    ensure_loaded()
    return jsonify(insights.revenue_opportunity_scan(_CACHE["df"], _CACHE["rfm"], _CACHE["churn_scores"]))


# ----------------------------------------------------------------------
# 5 & 12. Prediction Confidence + Forecast vs Actual Monitoring
#    (confidence is already embedded in /api/forecast's response)
# ----------------------------------------------------------------------
@app.route("/api/forecast-monitor")
def api_forecast_monitor():
    ensure_loaded()
    return jsonify(forecast_monitor.backtest_weekly(_CACHE["df"]))


# ----------------------------------------------------------------------
# 6. Smart Business Alerts — severity-tiered
# ----------------------------------------------------------------------
@app.route("/api/alerts-tiered")
def api_alerts_tiered():
    ensure_loaded()
    df = _CACHE["df"]
    kpis = insights.compute_kpis(df)
    regions = insights.regional_intelligence(df)
    matrix = insights.product_profitability_matrix(df)
    churn_df = _CACHE["churn_scores"]
    tiered = {"critical": [], "warning": [], "opportunity": []}

    if (kpis.get("growth_pct") or 0) < -10:
        tiered["critical"].append(f"Revenue dropped {abs(kpis['growth_pct'])}% vs last month.")
    for r in regions:
        if r["margin_pct"] < 8:
            tiered["critical"].append(f"{r['region']} profit margin critically low at {r['margin_pct']}%.")
        elif r["status"] == "Needs Attention":
            tiered["warning"].append(f"{r['region']} region growth slowed to {r['growth_pct']}%.")

    high_risk_pct = round(churn_df["risk_level"].eq("High Risk").mean() * 100, 1)
    if high_risk_pct > 15:
        tiered["warning"].append(f"{high_risk_pct}% increase in high-risk customers.")

    baskets = insights.market_basket(df, min_support=3, top_n=3)
    for b in baskets:
        tiered["opportunity"].append(f"'{b['product_a']}' + '{b['product_b']}' has strong cross-sell potential.")

    leak = insights.profit_leakage(df)
    for l in leak[:2]:
        tiered["critical"].append(f"Profit margin declined to {l['margin_pct']}% on '{l['product_name']}' due to heavy discounting.")

    return jsonify(tiered)


# ----------------------------------------------------------------------
# 7 & 8. Customer / Product Next-Best-Action
# ----------------------------------------------------------------------
@app.route("/api/next-best-action/customers")
def api_nba_customers():
    ensure_loaded()
    result = next_best_action.customer_next_best_action(_CACHE["rfm"], _CACHE["churn_scores"], _CACHE["clv"])
    if "clv_estimate" in result.columns:
        result = result.sort_values("clv_estimate", ascending=False)
    return jsonify(result.head(MAX_CUSTOMER_RECORDS).to_dict(orient="records"))


@app.route("/api/next-best-action/products")
def api_nba_products():
    ensure_loaded()
    matrix = insights.product_profitability_matrix(_CACHE["df"])
    return jsonify(next_best_action.product_next_best_action(matrix))


# ----------------------------------------------------------------------
# 9. Regional Opportunity Map (drill-down: region -> category -> product -> customer)
# ----------------------------------------------------------------------
@app.route("/api/region-drilldown/<region>")
def api_region_drilldown(region):
    ensure_loaded()
    return jsonify(insights.region_drilldown(_CACHE["df"], region))


# ----------------------------------------------------------------------
# 10. Data Detective
# ----------------------------------------------------------------------
@app.route("/api/data-detective")
def api_data_detective():
    ensure_loaded()
    return jsonify(insights.data_detective(_CACHE["df"], _CACHE["quality_report"]))


# ----------------------------------------------------------------------
# 13. Executive Command Center
# ----------------------------------------------------------------------
@app.route("/api/command-center")
def api_command_center():
    ensure_loaded()
    df = _CACHE["df"]
    kpis = insights.compute_kpis(df)
    regions = insights.regional_intelligence(df)
    matrix = insights.product_profitability_matrix(df)
    churn_summary = _CACHE["churn_scores"]["risk_level"].value_counts().to_dict()
    opps = insights.revenue_opportunity_scan(df, _CACHE["rfm"], _CACHE["churn_scores"])
    recs = insights.generate_recommendations(_CACHE["churn_scores"], matrix, regions)
    return jsonify(insights.command_center(kpis, regions, churn_summary, matrix, opps, recs))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=True (auto-reload + interactive traceback) is fine for local
    # dev, but must never run in production -- it lets anyone execute
    # arbitrary code through Flask's debugger. Render sets FLASK_DEBUG
    # itself if you ever want it on there; it's off by default.
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)