"""
AI-Powered Sales Forecasting.

Aggregates orders into a daily revenue series, fits a linear-trend +
day-of-week seasonality regression (scikit-learn), and projects revenue
for the next 7 / 30 / 90 days with an uncertainty band derived from the
model's residual standard deviation. Also returns actual-vs-predicted
for the historical window so accuracy can be visually inspected.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score


def _daily_series(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["order_status"] != "Cancelled"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    daily = d.groupby("order_date")["revenue"].sum().asfreq("D").fillna(0).reset_index()
    daily.columns = ["date", "revenue"]
    return daily


def _make_features(dates: pd.Series, t0: pd.Timestamp):
    t = (dates - t0).dt.days.values.reshape(-1, 1)
    dow = pd.get_dummies(dates.dt.dayofweek, prefix="dow")
    for i in range(7):
        col = f"dow_{i}"
        if col not in dow.columns:
            dow[col] = 0
    dow = dow[[f"dow_{i}" for i in range(7)]]
    X = np.hstack([t, dow.values])
    return X


def forecast_sales(df: pd.DataFrame, horizons=(7, 30, 90)):
    daily = _daily_series(df)
    t0 = daily["date"].min()
    X = _make_features(daily["date"], t0)
    y = daily["revenue"].values

    model = LinearRegression()
    model.fit(X, y)
    fitted = model.predict(X)
    residual_std = float(np.std(y - fitted))

    mae = round(mean_absolute_error(y, fitted), 2)
    r2 = round(r2_score(y, fitted), 3)

    last_date = daily["date"].max()
    max_h = max(horizons)
    future_dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=max_h, freq="D")
    Xf = _make_features(pd.Series(future_dates), t0)
    future_pred = model.predict(Xf)
    future_pred = np.clip(future_pred, a_min=0, a_max=None)

    # Coefficient of variation of the residuals drives a simple, explainable
    # confidence score: tighter residuals relative to average daily revenue
    # -> higher confidence. This is the "Prediction Confidence Center" number.
    avg_daily_revenue = float(np.mean(y)) or 1
    cv = residual_std / avg_daily_revenue
    base_confidence = max(35, min(97, round(100 - cv * 55)))

    results = {}
    for h in horizons:
        window = future_pred[:h]
        expected_revenue = round(float(window.sum()), 2)
        # widen uncertainty with horizon length (sqrt-of-time heuristic)
        margin = round(residual_std * np.sqrt(h) * 1.28, 2)  # ~80% band
        # confidence decays slightly for longer horizons (less certain further out)
        horizon_confidence = max(30, round(base_confidence - (h / max(horizons)) * 15))
        confidence_reason = (
            "Confidence is lower because recent sales volatility is higher relative to average daily revenue."
            if cv > 0.35 else
            "Confidence is solid — recent daily sales have been relatively stable."
        )
        results[f"next_{h}_days"] = {
            "expected_revenue": expected_revenue,
            "lower_bound": max(0, round(expected_revenue - margin, 2)),
            "upper_bound": round(expected_revenue + margin, 2),
            "avg_daily": round(expected_revenue / h, 2),
            "confidence_pct": horizon_confidence,
            "confidence_reason": confidence_reason,
        }

    trend_direction = "upward" if model.coef_[0] > 0 else "downward"

    history = daily.tail(120).copy()
    hist_fitted = fitted[-len(history):]
    actual_vs_predicted = [
        {"date": d.strftime("%Y-%m-%d"), "actual": round(a, 2), "predicted": round(p, 2)}
        for d, a, p in zip(history["date"], history["revenue"], hist_fitted)
    ]

    future_series = [
        {"date": d.strftime("%Y-%m-%d"), "predicted": round(p, 2)}
        for d, p in zip(future_dates[:30], future_pred[:30])
    ]

    return {
        "model": "LinearRegression (trend + day-of-week seasonality)",
        "mae": mae,
        "r2_score": r2,
        "trend_direction": trend_direction,
        "forecast": results,
        "actual_vs_predicted": actual_vs_predicted,
        "future_daily_forecast": future_series,
    }
