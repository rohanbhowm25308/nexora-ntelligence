# NEXORA Intelligence — Business Intelligence & Sales Analytics System

An end-to-end Business Intelligence & Predictive Analytics platform: upload a
sales dataset (or use the generated sample), and the system cleans it, stores
it in SQL, runs RFM segmentation + churn risk + CLV + sales forecasting with
scikit-learn, generates rule-based and Groq-LLM business insights, and
produces a one-click executive report — all behind a single dashboard.

## Stack
- **Backend:** Python, Flask, SQLite, Pandas, NumPy, Scikit-learn
- **Frontend:** HTML, CSS, vanilla JavaScript, Chart.js
- **LLM:** Groq API (Llama 3.3) for natural-language business insights
- **Data:** SQL analytics layer (`sql/queries.sql`) + a synthetic sample
  dataset generator (`data/generate_data.py`)

## Project structure
```
bi-system/
├── app.py                  # Flask app — all API routes
├── requirements.txt
├── .env.example             # copy to .env and add your Groq key
├── data/
│   ├── generate_data.py     # synthetic sample dataset generator
│   └── sales_data.csv       # generated on first run if missing
├── database/
│   └── db.py                 # SQLite schema + query helpers
├── ml/
│   ├── data_quality.py       # cleaning + quality scoring
│   ├── rfm.py                 # RFM segmentation, CLV, cohorts, behavior
│   ├── churn_model.py         # RandomForest churn/risk model
│   ├── forecast.py            # sales forecasting model
│   ├── insights.py            # KPIs, matrices, anomalies, recommendations
│   └── groq_client.py         # Groq LLM wrapper for narrative insights
├── sql/queries.sql           # reference SQL analytics queries
├── templates/                # index.html, dashboard.html, report.html
├── static/
│   ├── css/style.css
│   ├── js/app.js              # dashboard logic (fetch + Chart.js render)
│   ├── js/background.js       # animated global data-network background
│   └── js/world-dots.json     # land-mask dot coordinates for the background
└── tools/gen_world_dots.js   # (optional) regenerates world-dots.json
```

## Setup

```bash
cd bi-system
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your GROQ_API_KEY (free key: https://console.groq.com/keys)

python data/generate_data.py     # creates data/sales_data.csv (optional —
                                  # app.py auto-generates it on first run too)
python app.py
```

Open **http://localhost:5000**.

If `GROQ_API_KEY` is not set, the "AI Business Insights" and Executive Report
narrative automatically fall back to a rule-based summary — the app never
crashes because the key is missing.

## Using your own data

On the **Upload → Analyze → Report** tab, upload a CSV/XLSX with these
columns (extra/missing columns are tolerated — the cleaning pipeline fills
sensible defaults):

```
order_id, order_date, customer_id, customer_name, region, product_id,
product_name, category, quantity, unit_price, discount_pct, revenue,
cost, profit, payment_method, order_status
```

The pipeline runs: **validate → clean → SQLite → RFM/CLV → churn model →
forecast model → dashboard → insights → report**, exactly as described in
the project brief.

## What's implemented

### Command Center (new AI/decision-support layer)
- **AI Business Copilot** — a chat interface (`/api/copilot`) that answers questions like "Why did profit decrease this month?" or "Which customers are at risk?" using ONLY a JSON context bundle built from your live analytics (KPIs, regions, churn, root-cause, opportunities) — never generic AI knowledge. Falls back to a rule-based answer engine reading the same data if no Groq key is set.
- **What-If Business Simulator** — sliders for discount %, order volume, marketing budget, price, and retention rate project revenue/profit/margin impact in real time (`/api/simulate`), plus a **Scenario Comparison** table (Current vs. Proposed) (`/api/scenario-compare`).
- **Root-Cause Analysis Engine** — decomposes month-over-month profit change into ranked contributing factors (discounting, per-category margin shifts, per-region sales shifts) and names the primary driver (`/api/root-cause`).
- **Next-Best-Action** — every customer and every product gets one concrete recommended action derived from segment/risk/CLV or profitability quadrant (`/api/next-best-action/customers`, `/api/next-best-action/products`).
- **Executive Command Center** — single page with a 0–100 business health score, top 3 issues, and top 3 opportunities (`/api/command-center`).

### Enhanced existing modules
- **Prediction Confidence Center** — every forecast horizon now returns a confidence % and a plain-language reason (`/api/forecast`).
- **Forecast vs. Actual Monitoring** — rolling weekly backtest comparing forecast to actual with error % and an accuracy trend (`/api/forecast-monitor`).
- **Smart Business Alerts** — severity-tiered into Critical / Warning / Opportunity (`/api/alerts-tiered`), alongside the original flat alert feed.
- **Revenue Opportunity Scanner** — rupee-value-estimated opportunities (win-back campaigns, cross-sell bundles, region expansion, pricing optimization) (`/api/revenue-scan`).
- **Regional Opportunity Map** — click any region in the dashboard table to drill down Region → Category → Product → Customer (`/api/region-drilldown/<region>`).
- **Data Detective** — every upload gets a View → Explain → Fix issue list (missing values, duplicates, invalid dates, negative revenue, extreme discounts, outliers) (`/api/data-detective`).

### Original core features
- Executive KPI dashboard (revenue, profit, orders, AOV, margin, growth,
  repeat rate, revenue/customer)
- SQL analytics layer (`sql/queries.sql`, also executed live via `database/db.py`)
- RFM segmentation (VIP / Loyal / Potential Loyal / New / At Risk / Lost)
  with behavioral profiling and revenue contribution per segment
- Customer Lifetime Value estimation (High / Medium / Low tiers)
- Customer 360° profile lookup + purchase timeline
- Cohort retention analysis
- Churn/risk prediction: a RandomForestClassifier with a **Model Performance
  Center** (accuracy, F1, ROC-AUC, feature importance) and per-customer
  explainable risk factors
- Sales forecasting (7 / 30 / 90-day) with confidence bands and
  actual-vs-predicted charting
- Product profitability matrix (Stars / Profit Leaders / Revenue Drivers / Weak)
- Discount impact analysis, profit leakage detection, market basket analysis
- Seasonal demand intelligence (month / day-of-week patterns)
- Statistical anomaly detection (z-score based)
- Automated Groq-powered business insight narratives, with rule-based fallback
- Recommendation engine
- Business health scorecard
- KPI goal tracking (targets vs. actuals, achievement %)
- Automated data quality scoring on every upload
- One-click, narrated, downloadable executive report (`/api/report`)

## Notes on the background design

`static/js/background.js` renders the dark navy / electric-cyan global
data-network scene (world map dot-matrix, glowing connection arcs, digital
globe horizon, faint HUD panels) live on `<canvas>`, using real land-mass
coordinates in `static/js/world-dots.json` (derived from the open-source
`world-atlas` dataset via `tools/gen_world_dots.js`) rather than a static
photo — so it's crisp at any resolution, animated, and has zero page weight
from a background image.

## Suggested next steps for the internship submission

- Add a Jupyter notebook under `notebooks/` walking through the EDA and
  model evaluation for the write-up/demo video.
- Push to GitHub and fill in screenshots in this README.
- Record a 2–3 minute demo: Upload tab → Overview → Forecast → Churn →
  Segmentation → Executive Report.
# nexora-ntelligence
