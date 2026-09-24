/* ===================== NEXORA Dashboard Logic ===================== */
const Nexora = (() => {
  const CHART_CYAN = "#4fd8ff";
  const CHART_VIOLET = "#9a7bff";
  const CHART_GRID = "rgba(120,195,255,0.08)";
  const CHART_TEXT = "#93a6c9";
  const loaded = new Set();
  const charts = {};
  const CHARTS_AVAILABLE = typeof Chart !== "undefined";

  if (CHARTS_AVAILABLE) {
    Chart.defaults.color = CHART_TEXT;
    Chart.defaults.font.family = "Inter, sans-serif";
    Chart.defaults.borderColor = CHART_GRID;
  } else {
    // Chart.js failed to load (blocked script, offline, etc). Every other
    // part of the dashboard (tables, KPIs, simulator, copilot, etc.) must
    // still work — charts alone show a plain-text fallback instead.
    console.warn("NEXORA: Chart.js did not load — charts will show a text fallback; the rest of the dashboard is unaffected.");
  }

  function chartFallback(canvas, message) {
    if (!canvas || !canvas.parentElement) return;
    const note = document.createElement("div");
    note.style.cssText = "color:var(--text-3); font-size:0.82rem; padding:20px; text-align:center;";
    note.textContent = message || "Chart library unavailable — showing data in tables elsewhere on this page.";
    canvas.replaceWith(note);
  }

  function fmtINR(n) {
    if (n === null || n === undefined) return "—";
    return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
  }
  function fmtNum(n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("en-IN");
  }
  function badgeClass(level) {
    const l = (level || "").toLowerCase();
    if (l.includes("high")) return "high";
    if (l.includes("medium")) return "medium";
    if (l.includes("low")) return "low";
    if (l.includes("attention")) return "attention";
    if (l.includes("healthy")) return "healthy";
    return "neutral";
  }

  // ---------------------------------------------------------------- Text-to-Speech
  // Shared read-aloud helper for the chatbot and the AI-generated narrative
  // panels (Copilot, AI Insights, Root-Cause). Uses the browser's built-in
  // speech synthesis — no external API, works offline.
  const TTS_SUPPORTED = typeof window !== "undefined" && "speechSynthesis" in window;
  let lastCopilotAnswer = "";
  let copilotFallbackWarned = false;

  function speak(text, btnEl) {
    if (!TTS_SUPPORTED || !text) return;
    const isSpeaking = window.speechSynthesis.speaking;
    window.speechSynthesis.cancel();
    if (isSpeaking && btnEl && btnEl.dataset.wasSpeaking === "1") {
      // Clicking the same button that's currently speaking stops it.
      btnEl.dataset.wasSpeaking = "0";
      return;
    }
    const utter = new SpeechSynthesisUtterance(text.replace(/[🔊🤖👋⚠💡🔴🟡🔵🚨📈📊📄🧠✅❌]/gu, ""));
    utter.rate = 1;
    utter.pitch = 1;
    if (btnEl) {
      document.querySelectorAll("[data-tts-active]").forEach((el) => { el.removeAttribute("data-tts-active"); el.textContent = el.dataset.ttsLabel || el.textContent; });
      btnEl.dataset.wasSpeaking = "1";
      btnEl.setAttribute("data-tts-active", "1");
      utter.onend = () => { btnEl.removeAttribute("data-tts-active"); btnEl.dataset.wasSpeaking = "0"; };
      utter.onerror = () => { btnEl.removeAttribute("data-tts-active"); btnEl.dataset.wasSpeaking = "0"; };
    }
    window.speechSynthesis.speak(utter);
  }

  function speakElement(elId, btnEl) {
    const el = document.getElementById(elId);
    if (el) speak(el.textContent, btnEl || null);
  }

  function speakLastCopilotAnswer() {
    if (!lastCopilotAnswer) return;
    speak(lastCopilotAnswer, document.getElementById("copilot-speak-btn"));
  }

  // ---------------------------------------------------------------- Voice input (speech-to-text)
  // Lets the person speak their question into the Copilot instead of typing
  // it. Transcribed text is placed in the input box live, same as typing —
  // they still press Ask / Enter themselves to send it.
  const SR = typeof window !== "undefined" ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;
  let recognizer = null;
  let isListening = false;

  function toggleVoiceInput() {
    if (!SR) return;
    const btn = document.getElementById("copilot-mic-btn");
    const status = document.getElementById("copilot-mic-status");
    const input = document.getElementById("copilot-input");

    if (isListening) {
      recognizer && recognizer.stop();
      return;
    }

    recognizer = new SR();
    recognizer.lang = "en-US";
    recognizer.continuous = false;
    recognizer.interimResults = true;

    recognizer.onstart = () => {
      isListening = true;
      btn.classList.add("listening");
      status.classList.add("active");
    };
    recognizer.onresult = (e) => {
      let transcript = "";
      for (let i = 0; i < e.results.length; i++) transcript += e.results[i][0].transcript;
      input.value = transcript;
    };
    recognizer.onerror = () => {
      isListening = false;
      btn.classList.remove("listening");
      status.classList.remove("active");
    };
    recognizer.onend = () => {
      isListening = false;
      btn.classList.remove("listening");
      status.classList.remove("active");
      input.focus();
    };
    recognizer.start();
  }

  function go(view) {
    document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
    document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === "view-" + view));
    loadView(view);
  }

  function loadView(view) {
    if (loaded.has(view)) return;
    loaded.add(view);
    const fn = viewLoaders[view];
    if (fn) fn();
  }

  function destroyIfExists(canvas) {
    if (!CHARTS_AVAILABLE) return;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
  }

  function lineChart(ctx, labels, datasets, opts = {}) {
    if (!CHARTS_AVAILABLE) return chartFallback(ctx);
    destroyIfExists(ctx);
    return new Chart(ctx, {
      type: "line",
      data: { labels, datasets: datasets.map((d, i) => ({
        borderColor: i === 0 ? CHART_CYAN : CHART_VIOLET,
        backgroundColor: i === 0 ? "rgba(79,216,255,0.12)" : "rgba(154,123,255,0.12)",
        tension: 0.35, fill: true, pointRadius: 0, borderWidth: 2, ...d,
      })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: datasets.length > 1, labels: { boxWidth: 10 } } },
        scales: { x: { grid: { color: CHART_GRID } }, y: { grid: { color: CHART_GRID } } },
        ...opts,
      },
    });
  }

  function barChart(ctx, labels, datasets, opts = {}) {
    if (!CHARTS_AVAILABLE) return chartFallback(ctx);
    destroyIfExists(ctx);
    return new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: datasets.map((d, i) => ({
        backgroundColor: i === 0 ? "rgba(79,216,255,0.65)" : "rgba(154,123,255,0.65)",
        borderRadius: 6, ...d,
      })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: datasets.length > 1 } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: CHART_GRID } } },
        ...opts,
      },
    });
  }

  function doughnutChart(ctx, labels, values) {
    if (!CHARTS_AVAILABLE) return chartFallback(ctx);
    destroyIfExists(ctx);
    const palette = ["#4fd8ff", "#9a7bff", "#3ee6a8", "#ffc266", "#ff6b81", "#5d9dff"];
    return new Chart(ctx, {
      type: "doughnut",
      data: { labels, datasets: [{ data: values, backgroundColor: palette, borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } } },
    });
  }

  // ---------------------------------------------------------------- Overview
  async function loadOverview() {
    refreshDataStatus();
    // These four calls are independent of each other -- fetching them one
    // at a time (await, then await, then await...) adds up to four full
    // network round-trips in a row before anything on screen updates,
    // which is why the dashboard felt slow to "reload" after an upload
    // even for a small file (the delay is fixed per-request latency, not
    // dataset size). Running them together cuts that to the time of the
    // single slowest call instead of the sum of all four.
    const [kpis, topProducts, topCustomers, catPerf] = await Promise.all([
      fetch("/api/kpis").then((r) => r.json()),
      fetch("/api/sql/top_products").then((r) => r.json()),
      fetch("/api/sql/top_customers").then((r) => r.json()),
      fetch("/api/sql/category_performance").then((r) => r.json()),
    ]);
    const cards = [
      ["Total Revenue", fmtINR(kpis.total_revenue), kpis.growth_pct],
      ["Total Profit", fmtINR(kpis.total_profit), null],
      ["Total Orders", fmtNum(kpis.total_orders), null],
      ["Avg Order Value", fmtINR(kpis.aov), null],
      ["Profit Margin", kpis.profit_margin_pct + "%", null],
      ["Total Customers", fmtNum(kpis.total_customers), null],
      ["Repeat Customer Rate", kpis.repeat_customer_rate_pct + "%", null],
      ["Revenue / Customer", fmtINR(kpis.revenue_per_customer), null],
    ];
    document.getElementById("kpi-cards").innerHTML = cards.map(([label, value, growth]) => `
      <div class="card kpi-card">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        ${growth !== null && growth !== undefined ? `<div class="delta ${growth >= 0 ? "up" : "down"}">${growth >= 0 ? "▲" : "▼"} ${Math.abs(growth)}% MoM</div>` : ""}
      </div>`).join("");

    const months = kpis.monthly_trend.map((m) => m.month);
    lineChart(document.getElementById("chart-monthly-trend"), months, [
      { label: "Revenue", data: kpis.monthly_trend.map((m) => m.revenue) },
    ]);

    barChart(document.getElementById("chart-top-products"),
      topProducts.map((p) => p.product_name),
      [{ label: "Revenue", data: topProducts.map((p) => p.revenue) }],
      { indexAxis: "y", plugins: { legend: { display: false } } });

    document.getElementById("table-top-customers").innerHTML = topCustomers.map((c) => `
      <tr><td>${c.customer_name}</td><td>${c.total_orders}</td><td>${fmtINR(c.total_spent)}</td><td>${c.last_purchase}</td></tr>
    `).join("");

    doughnutChart(document.getElementById("chart-category"), catPerf.map((c) => c.category), catPerf.map((c) => c.revenue));
  }

  // ---------------------------------------------------------------- Forecast
  async function loadForecast() {
    const data = await fetch("/api/forecast").then((r) => r.json());
    const f = data.forecast;
    document.getElementById("forecast-cards").innerHTML = ["7", "30", "90"].map((h) => {
      const d = f["next_" + h + "_days"];
      return `<div class="card kpi-card">
        <div class="label">Next ${h} Days</div>
        <div class="value">${fmtINR(d.expected_revenue)}</div>
        <div class="delta up">Range: ${fmtINR(d.lower_bound)} – ${fmtINR(d.upper_bound)}</div>
        <div style="margin-top:8px; font-size:0.78rem; color:var(--text-2);">
          <span class="badge ${d.confidence_pct >= 65 ? 'low' : d.confidence_pct >= 45 ? 'medium' : 'high'}">Confidence: ${d.confidence_pct}%</span>
        </div>
        <div style="margin-top:6px; font-size:0.74rem; color:var(--text-3);">${d.confidence_reason}</div>
      </div>`;
    }).join("");

    document.getElementById("forecast-meta").innerText = `MAE ${data.mae} · R² ${data.r2_score} · ${data.trend_direction} trend`;

    const av = data.actual_vs_predicted;
    lineChart(document.getElementById("chart-actual-vs-predicted"), av.map((d) => d.date), [
      { label: "Actual", data: av.map((d) => d.actual), borderColor: CHART_CYAN, backgroundColor: "rgba(79,216,255,0.08)" },
      { label: "Predicted", data: av.map((d) => d.predicted), borderColor: CHART_VIOLET, backgroundColor: "rgba(154,123,255,0.08)", borderDash: [4, 3] },
    ]);

    const fut = data.future_daily_forecast;
    barChart(document.getElementById("chart-future-forecast"), fut.map((d) => d.date), [
      { label: "Predicted Revenue", data: fut.map((d) => d.predicted) },
    ], { plugins: { legend: { display: false } } });

    const mon = await fetch("/api/forecast-monitor").then((r) => r.json());
    if (mon.available) {
      document.getElementById("fm-accuracy").innerText = `Avg accuracy: ${mon.accuracy_pct}% · ${mon.trend}`;
      document.getElementById("table-forecast-monitor").innerHTML = mon.weeks.map((w) => `
        <tr><td>${w.week_ending}</td><td>${fmtINR(w.forecast)}</td><td>${fmtINR(w.actual)}</td>
        <td><span class="badge ${Math.abs(w.error_pct) <= 10 ? 'low' : Math.abs(w.error_pct) <= 25 ? 'medium' : 'high'}">${w.error_pct > 0 ? '+' : ''}${w.error_pct}%</span></td></tr>
      `).join("");
    } else {
      document.getElementById("fm-accuracy").innerText = "—";
      document.getElementById("table-forecast-monitor").innerHTML = `<tr><td colspan="4">${mon.reason}</td></tr>`;
    }
  }

  // ---------------------------------------------------------------- Alerts / Health
  async function loadAlerts() {
    const [health, alerts, tiered] = await Promise.all([
      fetch("/api/health-scorecard").then((r) => r.json()),
      fetch("/api/alerts").then((r) => r.json()),
      fetch("/api/alerts-tiered").then((r) => r.json()),
    ]);
    document.getElementById("table-health").innerHTML = health.map((h) => `
      <tr><td>${h.kpi}</td><td>${h.value}</td><td><span class="badge ${badgeClass(h.status)}">${h.status}</span></td></tr>
    `).join("");
    document.getElementById("alert-list").innerHTML = alerts.length
      ? alerts.map((a) => `<div class="alert-item"><span>${a.icon}</span><span>${a.message}</span></div>`).join("")
      : `<div class="alert-item">No active alerts — all metrics within normal range.</div>`;

    const fill = (id, items, empty) => {
      document.getElementById(id).innerHTML = items.length
        ? items.map((m) => `<div class="rec-item"><div class="action">${m}</div></div>`).join("")
        : `<div class="rec-item">${empty}</div>`;
    };
    fill("tiered-critical", tiered.critical, "No critical alerts.");
    fill("tiered-warning", tiered.warning, "No warnings.");
    fill("tiered-opportunity", tiered.opportunity, "No flagged opportunities right now.");
  }

  // ---------------------------------------------------------------- RFM
  async function loadSegments() {
    const data = await fetch("/api/rfm").then((r) => r.json());
    const seg = data.segment_summary;
    doughnutChart(document.getElementById("chart-rfm-segments"), seg.map((s) => s.segment), seg.map((s) => s.customers));
    barChart(document.getElementById("chart-rfm-revenue"), seg.map((s) => s.segment), [
      { label: "Revenue Share %", data: seg.map((s) => s.revenue_share_pct) },
    ], { plugins: { legend: { display: false } } });

    document.getElementById("table-rfm-customers").innerHTML = data.customers.slice(0, 60).map((c) => `
      <tr><td>${c.customer_name}</td><td>${c.rfm_score}</td><td>${c.segment_label}</td><td>${c.behavior_profile}</td>
      <td>${c.recency}d</td><td>${c.frequency}</td><td>${fmtINR(c.monetary)}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- Churn
  async function loadChurn() {
    const data = await fetch("/api/churn").then((r) => r.json());
    const summary = data.risk_summary;
    document.getElementById("risk-summary-cards").innerHTML = ["High Risk", "Medium Risk", "Low Risk"].map((lvl) => `
      <div class="card kpi-card">
        <div class="label">${lvl}</div>
        <div class="value">${summary[lvl] || 0}</div>
        <span class="badge ${badgeClass(lvl)}">${lvl}</span>
      </div>`).join("");

    const m = data.model_metrics;
    document.getElementById("model-metrics-body").innerHTML = m && m.accuracy !== undefined ? `
      <div class="grid cols-4">
        <div class="profile-field"><div class="k">Accuracy</div><div class="v">${m.accuracy}</div></div>
        <div class="profile-field"><div class="k">F1 Score</div><div class="v">${m.f1_score}</div></div>
        <div class="profile-field"><div class="k">ROC-AUC</div><div class="v">${m.roc_auc ?? "—"}</div></div>
        <div class="profile-field"><div class="k">Train / Test Rows</div><div class="v">${m.train_rows} / ${m.test_rows}</div></div>
      </div>
      <div style="margin-top:14px; font-size:0.85rem; color:var(--text-2);">
        Feature importance: ${Object.entries(m.feature_importance).map(([k, v]) => `${k} (${v})`).join(" · ")}
      </div>` : `<div style="color:var(--text-2);">${m?.note || "Rule-based scoring in use."}</div>`;

    const risky = data.customers.filter((c) => c.risk_level !== "Low Risk")
      .sort((a, b) => b.churn_probability - a.churn_probability).slice(0, 50);
    document.getElementById("table-churn").innerHTML = risky.map((c) => `
      <tr><td>${c.customer_name}</td><td>${c.segment}</td>
      <td><span class="badge ${badgeClass(c.risk_level)}">${c.risk_level}</span></td>
      <td>${(c.churn_probability * 100).toFixed(0)}%</td>
      <td style="font-size:0.78rem;color:var(--text-2);">${c.risk_factors.join(", ")}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- CLV
  async function loadCLV() {
    const data = await fetch("/api/clv").then((r) => r.json());
    document.getElementById("clv-summary-cards").innerHTML = data.tier_summary.map((t) => `
      <div class="card kpi-card">
        <div class="label">${t.clv_tier}</div>
        <div class="value">${t.customers}</div>
        <div class="delta up">Avg CLV: ${fmtINR(t.avg_clv)}</div>
      </div>`).join("");
    document.getElementById("table-clv").innerHTML = data.customers
      .sort((a, b) => b.clv_estimate - a.clv_estimate).slice(0, 60).map((c) => `
      <tr><td>${c.customer_name}</td><td>${fmtINR(c.clv_estimate)}</td>
      <td><span class="badge neutral">${c.clv_tier}</span></td><td>${c.segment}</td><td>${c.behavior_profile}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- Customer 360
  async function searchCustomer() {
    const id = document.getElementById("customer-search").value.trim();
    const box = document.getElementById("customer360-result");
    if (!id) return;
    box.innerHTML = `<div class="card">Loading…</div>`;
    const res = await fetch("/api/customer/" + encodeURIComponent(id));
    if (!res.ok) {
      let msg = `No customer found with ID "${id}".`;
      try { const err = await res.json(); if (err.error) msg = err.error; } catch (e) {}
      box.innerHTML = `<div class="card">${msg}</div>`;
      return;
    }
    const c = await res.json();
    box.innerHTML = `
      <div class="card section-block">
        <h3>${c.customer_name} <span class="tag">${c.customer_id}</span></h3>
        <div class="profile-grid">
          <div class="profile-field"><div class="k">Total Orders</div><div class="v">${c.total_orders}</div></div>
          <div class="profile-field"><div class="k">Total Spending</div><div class="v">${fmtINR(c.total_spending)}</div></div>
          <div class="profile-field"><div class="k">Avg Order Value</div><div class="v">${fmtINR(c.avg_order_value)}</div></div>
          <div class="profile-field"><div class="k">RFM Score</div><div class="v">${c.rfm_score}</div></div>
          <div class="profile-field"><div class="k">Segment</div><div class="v">${c.segment}</div></div>
          <div class="profile-field"><div class="k">Behavior Profile</div><div class="v">${c.behavior_profile}</div></div>
          <div class="profile-field"><div class="k">Risk Level</div><div class="v"><span class="badge ${badgeClass(c.risk_level)}">${c.risk_level}</span> (${(c.churn_probability*100).toFixed(0)}%)</div></div>
          <div class="profile-field"><div class="k">CLV Estimate</div><div class="v">${fmtINR(c.clv_estimate)} · ${c.clv_tier}</div></div>
          <div class="profile-field"><div class="k">Favorite Category</div><div class="v">${c.favorite_category}</div></div>
          <div class="profile-field"><div class="k">Favorite Product</div><div class="v">${c.favorite_product}</div></div>
          <div class="profile-field"><div class="k">First Purchase</div><div class="v">${c.first_purchase}</div></div>
          <div class="profile-field"><div class="k">Last Purchase</div><div class="v">${c.last_purchase}</div></div>
        </div>
        <div style="font-size:0.85rem; color:var(--text-2);">Why this risk level: ${c.risk_factors.join(", ")}</div>
      </div>
      <div class="card">
        <h3>Purchase Timeline</h3>
        <table><thead><tr><th>Date</th><th>Product</th><th>Revenue</th><th>Status</th></tr></thead>
        <tbody>${c.purchase_timeline.map((t) => `<tr><td>${t.order_date}</td><td>${t.product_name}</td><td>${fmtINR(t.revenue)}</td><td>${t.order_status}</td></tr>`).join("")}</tbody></table>
      </div>`;
  }

  // ---------------------------------------------------------------- Cohorts
  async function loadCohorts() {
    const rows = await fetch("/api/cohorts").then((r) => r.json());
    if (!rows.length) { document.getElementById("cohort-table").innerHTML = "<tr><td>No cohort data.</td></tr>"; return; }
    const periods = Object.keys(rows[0]).filter((k) => k !== "cohort_month").sort((a, b) => a - b);
    const head = `<tr><th>Cohort</th>${periods.map((p) => `<th>M${p}</th>`).join("")}</tr>`;
    const body = rows.map((r) => `<tr><td>${r.cohort_month}</td>${periods.map((p) => {
      const v = r[p];
      const opacity = v ? Math.min(1, v / 100) : 0;
      return `<td style="background: rgba(79,216,255,${opacity * 0.35})">${v ? v + "%" : "—"}</td>`;
    }).join("")}</tr>`).join("");
    document.getElementById("cohort-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  }

  // ---------------------------------------------------------------- Product Matrix
  async function loadProducts() {
    const data = await fetch("/api/product-matrix").then((r) => r.json());
    const quadrants = { "Stars": [], "Profit Leaders": [], "Revenue Drivers": [], "Weak": [] };
    data.forEach((p) => quadrants[p.quadrant] && quadrants[p.quadrant].push(p));
    const meta = {
      "Stars": "Low sales, high profit — hidden gems to promote",
      "Profit Leaders": "High sales, high profit — your best performers",
      "Revenue Drivers": "High sales, low profit — review pricing/discounts",
      "Weak": "Low sales, low profit — candidates to phase out",
    };
    document.getElementById("quadrant-grid").innerHTML = Object.entries(quadrants).map(([name, items]) => `
      <div class="quadrant">
        <h4>${name} <span style="color:var(--text-3); font-weight:400;">— ${meta[name]}</span></h4>
        ${items.sort((a, b) => b.revenue - a.revenue).slice(0, 12).map((p) => `
          <div class="prod-row"><span>${p.product_name}</span><span>${fmtINR(p.revenue)} rev / ${fmtINR(p.profit)} profit</span></div>
        `).join("") || '<div style="color:var(--text-3);">No products in this quadrant.</div>'}
      </div>`).join("");
  }

  // ---------------------------------------------------------------- Discounts
  async function loadDiscounts() {
    const data = await fetch("/api/discount-impact").then((r) => r.json());
    if (!CHARTS_AVAILABLE) { chartFallback(document.getElementById("chart-discount")); return; }
    destroyIfExists(document.getElementById("chart-discount"));
    new Chart(document.getElementById("chart-discount"), {
      data: {
        labels: data.map((d) => d.discount_band),
        datasets: [
          { type: "bar", label: "Revenue", data: data.map((d) => d.revenue), backgroundColor: "rgba(79,216,255,0.55)", yAxisID: "y" },
          { type: "line", label: "Margin %", data: data.map((d) => d.margin_pct), borderColor: "#ffc266", yAxisID: "y1", tension: 0.3 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: { y: { position: "left", grid: { color: CHART_GRID } }, y1: { position: "right", grid: { display: false } } },
      },
    });
  }

  // ---------------------------------------------------------------- Market Basket
  async function loadBasket() {
    const [basket, leakage] = await Promise.all([
      fetch("/api/market-basket").then((r) => r.json()),
      fetch("/api/profit-leakage").then((r) => r.json()),
    ]);
    document.getElementById("table-basket").innerHTML = basket.length
      ? basket.map((b) => `<tr><td>${b.product_a}</td><td>${b.product_b}</td><td>${b.times_bought_together}</td></tr>`).join("")
      : `<tr><td colspan="3">Not enough repeated co-purchases detected in this dataset yet.</td></tr>`;
    document.getElementById("table-leakage").innerHTML = leakage.length
      ? leakage.map((l) => `<tr><td>${l.product_name}</td><td>${l.category}</td><td>${fmtINR(l.revenue)}</td><td>${(l.avg_discount*100).toFixed(0)}%</td><td>${l.margin_pct}%</td></tr>`).join("")
      : `<tr><td colspan="5">No significant profit leakage detected.</td></tr>`;
  }

  // ---------------------------------------------------------------- Regions
  async function loadRegions() {
    const data = await fetch("/api/regions").then((r) => r.json());
    document.getElementById("table-regions").innerHTML = data.map((r) => `
      <tr style="cursor:pointer;" onclick="Nexora.drillRegion('${r.region}')">
      <td>${r.region} 🔎</td><td>${fmtINR(r.revenue)}</td><td>${fmtINR(r.profit)}</td><td>${r.orders}</td>
      <td>${r.customers}</td><td>${fmtINR(r.aov)}</td><td>${r.margin_pct}%</td><td>${r.growth_pct}%</td>
      <td><span class="badge ${badgeClass(r.status)}">${r.status}</span></td></tr>`).join("");
  }

  async function drillRegion(region) {
    const box = document.getElementById("region-drilldown");
    box.innerHTML = `<div class="card">Loading ${region}…</div>`;
    const data = await fetch("/api/region-drilldown/" + encodeURIComponent(region)).then((r) => r.json());
    if (!data.found) { box.innerHTML = `<div class="card">No data for ${region}.</div>`; return; }
    box.innerHTML = `
      <div class="grid cols-3" style="margin-top:16px;">
        <div class="card">
          <h3>${region} — By Category</h3>
          <table><thead><tr><th>Category</th><th>Revenue</th><th>Profit</th></tr></thead>
          <tbody>${data.categories.map((c) => `<tr><td>${c.category}</td><td>${fmtINR(c.revenue)}</td><td>${fmtINR(c.profit)}</td></tr>`).join("")}</tbody></table>
        </div>
        <div class="card">
          <h3>${region} — Top Products</h3>
          <table><thead><tr><th>Product</th><th>Revenue</th></tr></thead>
          <tbody>${data.products.slice(0, 8).map((p) => `<tr><td>${p.product_name}</td><td>${fmtINR(p.revenue)}</td></tr>`).join("")}</tbody></table>
        </div>
        <div class="card">
          <h3>${region} — Top Customers</h3>
          <table><thead><tr><th>Customer</th><th>Revenue</th></tr></thead>
          <tbody>${data.customers.slice(0, 8).map((c) => `<tr><td>${c.customer_name}</td><td>${fmtINR(c.revenue)}</td></tr>`).join("")}</tbody></table>
        </div>
      </div>`;
  }

  // ---------------------------------------------------------------- Seasonality
  async function loadSeasonality() {
    const data = await fetch("/api/seasonality").then((r) => r.json());
    const months = Object.keys(data.high_demand_months).concat(Object.keys(data.low_demand_months));
    barChart(document.getElementById("chart-season-month"),
      [...new Set(months)],
      [{ label: "Revenue", data: [...new Set(months)].map((m) => data.high_demand_months[m] ?? data.low_demand_months[m]) }],
      { plugins: { legend: { display: false } } });
    const dow = data.day_of_week_pattern;
    barChart(document.getElementById("chart-season-dow"), Object.keys(dow), [
      { label: "Revenue", data: Object.values(dow) },
    ], { plugins: { legend: { display: false } } });
  }

  // ---------------------------------------------------------------- AI Insights
  async function loadInsights() {
    const [ai, opp] = await Promise.all([
      fetch("/api/ai-insights").then((r) => r.json()),
      fetch("/api/opportunities").then((r) => r.json()),
    ]);
    document.getElementById("ai-insight-text").innerText = ai.insights + (ai.source === "rule-based-fallback" ? `\n\n(Groq AI unavailable — ${ai.groq_configured ? "request failed: " + ai.note : "no API key configured on the server"}. Showing a rule-based summary instead.)` : "");
    document.getElementById("table-opportunities").innerHTML = opp.map((o) => `
      <tr><td>${o.opportunity}</td><td>${o.potential_impact}</td><td>${o.reason}</td><td>${o.recommended_action}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- Revenue Scanner
  async function loadRevenueScan() {
    const data = await fetch("/api/revenue-scan").then((r) => r.json());
    document.getElementById("revenue-scan-cards").innerHTML = data.map((o) => `
      <div class="card">
        <h3>${o.opportunity}</h3>
        <div class="value" style="font-family:var(--font-display); font-size:1.3rem; color:var(--cyan-bright); margin-bottom:10px;">${o.potential_impact}</div>
        <div style="color:var(--text-2); font-size:0.85rem; margin-bottom:8px;">${o.reason}</div>
        <div style="font-size:0.85rem; font-weight:600;">→ ${o.recommended_action}</div>
      </div>`).join("") || `<div class="card">No opportunities flagged right now.</div>`;
  }

  // ---------------------------------------------------------------- Executive Command Center
  async function loadCommandCenter() {
    const data = await fetch("/api/command-center").then((r) => r.json());
    document.getElementById("cc-health-score").innerText = data.health_score + "/100";
    document.getElementById("cc-health-status").innerHTML = `<span class="badge ${badgeClass(data.health_status)}">${data.health_status}</span>`;
    document.getElementById("cc-customers").innerText = fmtNum(data.total_customers);
    document.getElementById("cc-at-risk").innerText = fmtNum(data.at_risk_customers);

    const k = data.kpis;
    document.getElementById("cc-kpi-cards").innerHTML = [
      ["Revenue", fmtINR(k.total_revenue)], ["Profit", fmtINR(k.total_profit)],
      ["Growth", (k.growth_pct ?? 0) + "%"], ["Forecast Trend", k.growth_pct >= 0 ? "▲ Positive" : "▼ Negative"],
    ].map(([l, v]) => `<div class="card kpi-card"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("");

    document.getElementById("cc-issues").innerHTML = data.top_issues.map((t) => `<div class="rec-item"><div class="action">⚠ ${t}</div></div>`).join("");
    document.getElementById("cc-opportunities").innerHTML = data.top_opportunities.map((t) => `<div class="rec-item"><div class="action">💡 ${t}</div></div>`).join("");
  }

  // ---------------------------------------------------------------- AI Business Copilot
  async function loadCopilot() {
    const suggestions = await fetch("/api/copilot/suggestions").then((r) => r.json());
    document.getElementById("copilot-suggestions").innerHTML = suggestions.map((s) => `
      <button class="icon-btn" style="font-size:0.78rem;" onclick="Nexora.askCopilot('${s.replace(/'/g, "\\'")}')">${s}</button>
    `).join("");
  }

  async function askCopilot(preset) {
    const input = document.getElementById("copilot-input");
    const question = preset || input.value.trim();
    if (!question) return;
    input.value = "";
    const chat = document.getElementById("copilot-chat");
    chat.insertAdjacentHTML("beforeend", `<div class="alert-item" style="align-self:flex-end; background:rgba(79,216,255,0.14); max-width:80%;">${question}</div>`);
    const loadingId = "load-" + Date.now();
    chat.insertAdjacentHTML("beforeend", `<div class="alert-item" id="${loadingId}" style="background:rgba(255,255,255,0.03);">Thinking…</div>`);
    chat.scrollTop = chat.scrollHeight;

    const res = await fetch("/api/copilot", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) }).then((r) => r.json());
    lastCopilotAnswer = res.answer;
    const msgId = "msg-" + Date.now();
    const fallbackWarning = res.source === "rule-based-fallback" && !copilotFallbackWarned
      ? (copilotFallbackWarned = true,
         `<div style="font-size:0.72rem; color:var(--warn,#ffc266); margin-top:6px;">⚠️ Groq AI is unavailable right now (${res.groq_configured ? "request failed" : "no API key configured on the server"}) — showing a basic data summary instead of a full AI answer. Check the server terminal for the exact error.</div>`)
      : "";
    document.getElementById(loadingId).outerHTML = `
      <div class="alert-item" style="background:rgba(255,255,255,0.03); align-items:flex-start; gap:10px;">
        <span style="flex:1;" id="${msgId}">🤖 ${res.answer}${fallbackWarning}</span>
        <button class="icon-btn" title="Read this answer aloud" onclick="Nexora.speak(document.getElementById('${msgId}').textContent, this)" style="flex-shrink:0; padding:5px 9px; font-size:0.75rem;">🔊</button>
      </div>`;
    chat.scrollTop = chat.scrollHeight;
  }

  // ---------------------------------------------------------------- What-If Simulator
  let simKpis = null;
  async function loadSimulator() {
    simKpis = await fetch("/api/kpis").then((r) => r.json());
    runSimulator();
  }

  async function runSimulator() {
    const params = {
      discount_delta_pct: +document.getElementById("sim-discount").value,
      orders_delta_pct: +document.getElementById("sim-orders").value,
      marketing_delta_pct: +document.getElementById("sim-marketing").value,
      price_delta_pct: +document.getElementById("sim-price").value,
      retention_delta_pct: +document.getElementById("sim-retention").value,
    };
    document.getElementById("sim-discount-val").innerText = params.discount_delta_pct + "%";
    document.getElementById("sim-orders-val").innerText = params.orders_delta_pct + "%";
    document.getElementById("sim-marketing-val").innerText = params.marketing_delta_pct + "%";
    document.getElementById("sim-price-val").innerText = params.price_delta_pct + "%";
    document.getElementById("sim-retention-val").innerText = params.retention_delta_pct + "%";

    const result = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) }).then((r) => r.json());
    const p = result.projected, im = result.impact;
    document.getElementById("sim-results").innerHTML = `
      <div class="profile-field"><div class="k">Projected Revenue</div><div class="v">${fmtINR(p.revenue)}</div><div class="delta ${im.revenue_change >= 0 ? 'up' : 'down'}">${im.revenue_change >= 0 ? '+' : ''}${fmtINR(im.revenue_change)} (${im.revenue_change_pct}%)</div></div>
      <div class="profile-field"><div class="k">Projected Profit</div><div class="v">${fmtINR(p.profit)}</div><div class="delta ${im.profit_change >= 0 ? 'up' : 'down'}">${im.profit_change >= 0 ? '+' : ''}${fmtINR(im.profit_change)} (${im.profit_change_pct}%)</div></div>
      <div class="profile-field"><div class="k">Projected Margin</div><div class="v">${p.margin_pct}%</div><div class="delta ${im.margin_change_pp >= 0 ? 'up' : 'down'}">${im.margin_change_pp >= 0 ? '+' : ''}${im.margin_change_pp} pp</div></div>
      <div class="profile-field"><div class="k">Projected Orders</div><div class="v">${fmtNum(p.orders)}</div></div>
    `;

    const cmp = await fetch("/api/scenario-compare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_a: {}, scenario_b: params }),
    }).then((r) => r.json());
    const rows = [
      ["Revenue", fmtINR(cmp.scenario_a.revenue), fmtINR(cmp.scenario_b.revenue), fmtINR(cmp.delta.revenue)],
      ["Profit", fmtINR(cmp.scenario_a.profit), fmtINR(cmp.scenario_b.profit), fmtINR(cmp.delta.profit)],
      ["Margin %", cmp.scenario_a.margin_pct + "%", cmp.scenario_b.margin_pct + "%", cmp.delta.margin_pct + " pp"],
      ["Customers", fmtNum(cmp.scenario_a.customers), fmtNum(cmp.scenario_b.customers), (cmp.delta.customers >= 0 ? "+" : "") + fmtNum(cmp.delta.customers)],
    ];
    document.getElementById("table-scenario").innerHTML = rows.map(([label, a, b, d]) => `
      <tr><td>${label}</td><td>${a}</td><td>${b}</td><td>${d}</td></tr>
    `).join("");
  }

  function resetSimulator() {
    ["sim-discount", "sim-orders", "sim-marketing", "sim-price", "sim-retention"].forEach((id) => { document.getElementById(id).value = 0; });
    runSimulator();
  }

  // ---------------------------------------------------------------- Root-Cause Analysis
  async function loadRootCause() {
    const data = await fetch("/api/root-cause").then((r) => r.json());
    if (!data.available) {
      document.getElementById("rc-summary").innerHTML = `<div style="color:var(--text-2);">${data.reason}</div>`;
      document.getElementById("table-rootcause").innerHTML = `<tr><td colspan="2">—</td></tr>`;
      return;
    }
    document.getElementById("rc-summary").innerHTML = `
      <h3 style="display:flex; align-items:center; justify-content:space-between;">
        <span>Profit ${data.profit_change_pct >= 0 ? '↑' : '↓'} ${Math.abs(data.profit_change_pct)}% <span class="tag">${data.period.previous} → ${data.period.current}</span></span>
        <button class="icon-btn" title="Read the primary driver aloud" onclick="Nexora.speakElement('rc-driver-text', this)" style="padding:7px 12px; font-size:0.78rem;">🔊 Listen</button>
      </h3>
      <div class="insight-box" id="rc-driver-text">Primary Driver: ${data.primary_driver}</div>`;
    document.getElementById("table-rootcause").innerHTML = data.factors.map((f) => `
      <tr><td><b>${f.factor}</b></td><td>${f.detail}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- Next-Best-Action
  async function loadNBA() {
    const [customers, products] = await Promise.all([
      fetch("/api/next-best-action/customers").then((r) => r.json()),
      fetch("/api/next-best-action/products").then((r) => r.json()),
    ]);
    document.getElementById("table-nba-customers").innerHTML = customers
      .sort((a, b) => b.clv_estimate - a.clv_estimate).slice(0, 40).map((c) => `
      <tr><td>${c.customer_name}</td><td>${c.segment}</td>
      <td><span class="badge ${badgeClass(c.risk_level)}">${c.risk_level}</span></td>
      <td>${fmtINR(c.clv_estimate)}</td><td>${c.recommended_action}</td></tr>
    `).join("");
    document.getElementById("table-nba-products").innerHTML = products.map((p) => `
      <tr><td>${p.product_name}</td><td>${fmtINR(p.revenue)}</td><td>${fmtINR(p.profit)}</td>
      <td><span class="badge neutral">${p.quadrant}</span></td><td>${p.recommended_action}</td></tr>
    `).join("");
  }

  // ---------------------------------------------------------------- Recommendations
  async function loadRecommendations() {
    const data = await fetch("/api/recommendations").then((r) => r.json());
    document.getElementById("rec-list").innerHTML = data.length
      ? data.map((r) => `<div class="rec-item"><div class="problem">⚠ ${r.problem}</div><div class="action">→ ${r.recommendation}</div></div>`).join("")
      : `<div class="rec-item">No urgent recommendations right now — key metrics look healthy.</div>`;
  }

  // ---------------------------------------------------------------- Anomalies
  async function loadAnomalies() {
    const data = await fetch("/api/anomalies").then((r) => r.json());
    document.getElementById("table-anomalies").innerHTML = data.length
      ? data.map((a) => `<tr><td>${a.date}</td><td>${a.metric}</td><td>${fmtNum(a.value)}</td><td>🚨 ${a.type}</td></tr>`).join("")
      : `<tr><td colspan="4">No significant anomalies detected.</td></tr>`;
  }

  // ---------------------------------------------------------------- Goals
  async function loadGoals() {
    const data = await fetch("/api/goals").then((r) => r.json());
    document.getElementById("goal-revenue").value = data.revenue.target || "";
    document.getElementById("goal-profit").value = data.profit.target || "";
    document.getElementById("goal-orders").value = data.orders.target || "";
    renderGoalCards(data);
  }
  function renderGoalCards(data) {
    const rows = [["Revenue", data.revenue, fmtINR], ["Profit", data.profit, fmtINR], ["Orders", data.orders, fmtNum]];
    document.getElementById("goal-progress-cards").innerHTML = rows.map(([label, d, fmt]) => `
      <div class="card kpi-card">
        <div class="label">${label} — Actual vs Target</div>
        <div class="value">${fmt(d.actual)} <span style="font-size:0.9rem; color:var(--text-3);">/ ${fmt(d.target)}</span></div>
        <div class="progress-bar"><div style="width:${Math.min(100, d.achievement_pct)}%"></div></div>
        <div class="delta ${d.gap <= 0 ? "up" : "down"}" style="margin-top:8px;">${d.achievement_pct}% achieved · Gap: ${fmt(Math.max(0, d.gap))}</div>
      </div>`).join("");
  }
  async function saveGoals() {
    const body = {
      revenue_target: document.getElementById("goal-revenue").value || 0,
      profit_target: document.getElementById("goal-profit").value || 0,
      orders_target: document.getElementById("goal-orders").value || 0,
    };
    const data = await fetch("/api/goals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
    renderGoalCards(data);
  }

  // ---------------------------------------------------------------- Upload
  async function uploadFile(file) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    document.getElementById("quality-report-body").innerHTML = `<span style="color:var(--text-2);">Uploading &amp; processing "${file.name}"… this usually takes a few seconds.</span>`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90000); // 90s safety timeout

    try {
      const res = await fetch("/api/upload", { method: "POST", body, signal: controller.signal });
      clearTimeout(timeoutId);

      let data;
      try {
        data = await res.json();
      } catch (parseErr) {
        throw new Error(`Server returned an unexpected response (status ${res.status}). Please try again.`);
      }

      if (!res.ok || data.error) {
        document.getElementById("quality-report-body").innerHTML = `<span style="color:var(--danger);">⚠ ${data.error || "Upload failed. Please check the file and try again."}</span>`;
        return;
      }

      renderQuality(data.quality_report);
      loadDetective();
      loaded.clear();
      loaded.add("upload"); // already rendered above -- don't make loadUpload() re-fetch the same data-quality/detective calls a second time
      loadOverview();
      loadReport(); // refresh the report iframe now too, in case it's already open
      loaded.add("report");
      refreshDataStatus();
    } catch (err) {
      clearTimeout(timeoutId);
      const msg = err.name === "AbortError"
        ? "Upload timed out after 90 seconds. Try a smaller file, or check your connection and try again."
        : (err.message || "Upload failed. Please try again.");
      document.getElementById("quality-report-body").innerHTML = `<span style="color:var(--danger);">⚠ ${msg}</span>`;
    } finally {
      document.getElementById("file-input").value = "";
    }
  }
  function renderQuality(q) {
    document.getElementById("quality-report-body").innerHTML = `
      <div class="grid cols-4">
        <div class="profile-field"><div class="k">Data Quality Score</div><div class="v">${q.quality_score}%</div></div>
        <div class="profile-field"><div class="k">Rows Analyzed</div><div class="v">${q.rows_in}</div></div>
        <div class="profile-field"><div class="k">Rows After Cleaning</div><div class="v">${q.rows_out}</div></div>
        <div class="profile-field"><div class="k">Missing Values</div><div class="v">${q.missing_values}</div></div>
        <div class="profile-field"><div class="k">Duplicate Records</div><div class="v">${q.duplicate_records}</div></div>
        <div class="profile-field"><div class="k">Invalid Dates</div><div class="v">${q.invalid_dates}</div></div>
        <div class="profile-field"><div class="k">Invalid Numeric Values</div><div class="v">${q.invalid_numeric_values}</div></div>
        <div class="profile-field"><div class="k">Outliers Flagged</div><div class="v">${q.statistical_outliers_flagged}</div></div>
      </div>`;
  }
  async function loadDetective() {
    const data = await fetch("/api/data-detective").then((r) => r.json());
    document.getElementById("detective-count").innerText = `${data.issues_found} issue(s) found`;
    document.getElementById("detective-list").innerHTML = data.issues.map((i) => `
      <div class="rec-item">
        <div class="problem"><span class="badge ${i.severity === 'High' ? 'high' : i.severity === 'Medium' ? 'medium' : i.severity === 'Low' ? 'low' : 'neutral'}">${i.severity}</span> ${i.issue}</div>
        <div style="font-size:0.82rem; color:var(--text-2); margin-top:6px;"><b>Explain:</b> ${i.explain}</div>
        <div style="font-size:0.82rem; color:var(--cyan-bright); margin-top:4px;"><b>Fix:</b> ${i.fix}</div>
      </div>`).join("");
  }
  function loadReport() {
    // The report lives in an iframe (it's server-rendered HTML, not JSON),
    // so it isn't covered by a fetch() call the way other views are. Point
    // it at /api/report fresh every time this view loads (cache-busted)
    // instead of relying on a static src, otherwise it keeps showing
    // whatever dataset was active the very first time the iframe was
    // parsed (usually the demo data), even after a new CSV is uploaded.
    const frame = document.getElementById("report-iframe");
    if (frame) frame.src = "/api/report?t=" + Date.now();
  }
  async function loadUpload() {
    const q = await fetch("/api/data-quality").then((r) => r.json());
    renderQuality(q);
    loadDetective();
    refreshDataStatus();
  }

  async function loadDemoData() {
    document.getElementById("quality-report-body").innerText = "Loading demo dataset…";
    try {
      const res = await fetch("/api/load-demo", { method: "POST" });
      let data;
      try {
        data = await res.json();
      } catch (e) {
        throw new Error(`Server returned an unexpected response (status ${res.status}).`);
      }
      if (!res.ok || data.error) {
        document.getElementById("quality-report-body").innerHTML = `<span style="color:var(--danger);">⚠ ${data.error || "Could not load the demo dataset."}</span>`;
        return;
      }
      renderQuality(data.quality_report);
      loadDetective();
      loaded.clear();
      loaded.add("upload"); // already rendered above -- avoid a redundant re-fetch
      loadOverview();
      refreshDataStatus();
    } catch (err) {
      document.getElementById("quality-report-body").innerHTML = `<span style="color:var(--danger);">⚠ ${err.message || "Could not load the demo dataset."}</span>`;
    }
  }

  async function refreshDataStatus() {
    const status = await fetch("/api/data-status").then((r) => r.json());
    const demoBanner = document.getElementById("demo-banner");
    if (demoBanner) demoBanner.style.display = status.is_demo ? "flex" : "none";

    const uploadBanner = document.getElementById("upload-status-banner");
    if (uploadBanner) {
      if (status.is_demo) {
        uploadBanner.style.background = "rgba(255,194,102,0.08)";
        uploadBanner.style.borderColor = "rgba(255,194,102,0.28)";
        uploadBanner.innerHTML = `<span>🧪 Currently showing <strong>demo data</strong> (${status.rows.toLocaleString()} rows, auto-generated). Upload your own file above to replace it.</span>`;
      } else {
        uploadBanner.style.background = "rgba(62,230,168,0.08)";
        uploadBanner.style.borderColor = "rgba(62,230,168,0.28)";
        uploadBanner.innerHTML = `<span>✅ Currently showing <strong>your data</strong> — ${status.source_filename} (${status.rows.toLocaleString()} rows).</span>`;
      }
    }
    return status;
  }

  const viewLoaders = {
    overview: loadOverview, forecast: loadForecast, alerts: loadAlerts,
    segments: loadSegments, churn: loadChurn, clv: loadCLV, cohorts: loadCohorts,
    products: loadProducts, discounts: loadDiscounts, basket: loadBasket,
    regions: loadRegions, seasonality: loadSeasonality, insights: loadInsights,
    recommendations: loadRecommendations, anomalies: loadAnomalies, goals: loadGoals,
    upload: loadUpload, revenuescan: loadRevenueScan, commandcenter: loadCommandCenter, report: loadReport,
    copilot: loadCopilot, simulator: loadSimulator, rootcause: loadRootCause, nba: loadNBA,
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".nav-item").forEach((el) => el.addEventListener("click", () => go(el.dataset.view)));
    const hashView = window.location.hash ? window.location.hash.slice(1) : "";
    const startView = hashView && document.getElementById("view-" + hashView) ? hashView : "overview";
    go(startView);
    refreshDataStatus();
    if (!TTS_SUPPORTED) {
      const btn = document.getElementById("copilot-speak-btn");
      if (btn) btn.style.display = "none";
    }
    if (!SR) {
      const mic = document.getElementById("copilot-mic-btn");
      if (mic) mic.style.display = "none";
    }
  });

  return { go, searchCustomer, saveGoals, uploadFile, loadDemoData, drillRegion, askCopilot, runSimulator, resetSimulator, speak, speakElement, speakLastCopilotAnswer, toggleVoiceInput };
})();