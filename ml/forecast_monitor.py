"""
Forecast vs. Actual Monitoring.

Backtests the sales-forecasting model over recent history: for each of
the last N weeks, fit the model on data up to that point and predict the
following week, then compare against what actually happened. This gives
a rolling forecast-error track record instead of a single static number.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from ml.forecast import _daily_series, _make_features


def backtest_weekly(df: pd.DataFrame, weeks: int = 8) -> dict:
    daily = _daily_series(df)
    if len(daily) < 30:
        return {"available": False, "reason": "Not enough historical data to backtest yet."}

    results = []
    step = 7
    # Walk backward in 7-day blocks, always training only on data before the block.
    usable_weeks = min(weeks, (len(daily) - 14) // step)
    for i in range(usable_weeks, 0, -1):
        cutoff = len(daily) - i * step
        train = daily.iloc[:cutoff]
        test = daily.iloc[cutoff:cutoff + step]
        if len(train) < 14 or len(test) == 0:
            continue

        t0 = train["date"].min()
        X_train = _make_features(train["date"], t0)
        y_train = train["revenue"].values
        model = LinearRegression().fit(X_train, y_train)

        X_test = _make_features(test["date"], t0)
        pred = np.clip(model.predict(X_test), 0, None)

        actual_sum = float(test["revenue"].sum())
        pred_sum = float(pred.sum())
        error_pct = round((pred_sum - actual_sum) / actual_sum * 100, 1) if actual_sum else 0

        results.append({
            "week_ending": test["date"].max().strftime("%Y-%m-%d"),
            "forecast": round(pred_sum, 2),
            "actual": round(actual_sum, 2),
            "error_pct": error_pct,
        })

    if not results:
        return {"available": False, "reason": "Not enough historical data to backtest yet."}

    errors = [abs(r["error_pct"]) for r in results]
    mae_pct = round(sum(errors) / len(errors), 2)
    trend = "improving" if len(errors) >= 4 and sum(errors[-2:]) < sum(errors[:2]) else "stable"

    return {
        "available": True,
        "weeks": results,
        "avg_abs_error_pct": mae_pct,
        "accuracy_pct": round(max(0, 100 - mae_pct), 1),
        "trend": trend,
    }
