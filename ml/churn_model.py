"""
Customer Churn & Risk Prediction.

Trains a RandomForestClassifier on engineered RFM-style behavioral
features. Since we don't have ground-truth "churned" labels, we build a
reasonable proxy label (a customer is "churned" if their recency is in
the worst quartile and frequency is low) purely to TRAIN the model in a
supervised way -- then use the model's predicted probability, together
with transparent rule-based factors, to produce the final Low/Medium/High
risk label and a human-readable explanation. This keeps the risk score
both ML-driven and explainable, which is what the brief asks for.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import os

# On Render, joblib's multiprocess backend (n_jobs>1) forks extra worker
# processes that each duplicate the training data in memory -- fine on a
# dev machine with several GB of RAM, but risky on Render's resource-capped
# free tier (~512MB), where it can push memory over the limit and get the
# whole process OOM-killed. Locally there's no such constraint, so use full
# parallelism there for speed. Render always sets RENDER=true at runtime
# (see https://render.com/docs/environment-variables), so this switches
# automatically -- no manual tuning needed either way.
_N_JOBS = 1 if os.environ.get("RENDER") else -1

FEATURES = ["recency", "frequency", "monetary", "avg_order_value", "avg_discount", "rfm_total"]


def build_features(rfm_df: pd.DataFrame) -> pd.DataFrame:
    d = rfm_df.copy()
    med_recency = d["recency"].median()
    # Proxy label for supervised training only
    d["_churn_label"] = ((d["recency"] > d["recency"].quantile(0.75)) & (d["frequency"] <= d["frequency"].median())).astype(int)
    return d


def train_churn_model(rfm_df: pd.DataFrame):
    d = build_features(rfm_df)
    X = d[FEATURES].fillna(0)
    y = d["_churn_label"]

    if y.nunique() < 2 or len(d) < 20:
        # Not enough signal/data to train meaningfully; fall back to rule-based only
        return None, {"note": "Insufficient data variety to train ML model; using rule-based risk only."}

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
    model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42, class_weight="balanced", n_jobs=_N_JOBS)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]
    metrics = {
        "model": "RandomForestClassifier",
        "features_used": FEATURES,
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "accuracy": round(accuracy_score(y_test, preds), 3),
        "f1_score": round(f1_score(y_test, preds), 3),
        "roc_auc": round(roc_auc_score(y_test, probs), 3) if y_test.nunique() > 1 else None,
        "feature_importance": dict(sorted(
            zip(FEATURES, model.feature_importances_.round(3).tolist()),
            key=lambda x: -x[1]
        )),
    }
    return model, metrics


def score_customers(rfm_df: pd.DataFrame, model=None) -> pd.DataFrame:
    d = build_features(rfm_df)
    X = d[FEATURES].fillna(0)

    if model is not None:
        d["churn_probability"] = model.predict_proba(X)[:, 1].round(3)
    else:
        # rule-based fallback probability. np.clip (not Series.max().clip)
        # because .max() can return a plain Python float on tiny/edge-case
        # datasets, and a Python float has no .clip() method.
        recency_max = max(float(d["recency"].max()), 1)
        frequency_max = max(float(d["frequency"].max()), 1)
        monetary_max = max(float(d["monetary"].max()), 1)
        d["churn_probability"] = (
            0.5 * (d["recency"] / recency_max) +
            0.3 * (1 - d["frequency"] / frequency_max) +
            0.2 * (1 - d["monetary"] / monetary_max)
        ).round(3)

    def risk_level(p):
        if p >= 0.66:
            return "High Risk"
        if p >= 0.33:
            return "Medium Risk"
        return "Low Risk"

    d["risk_level"] = d["churn_probability"].apply(risk_level)

    def reasons(row):
        r = []
        if row["recency"] > 90:
            r.append(f"{int(row['recency'])} days since last purchase")
        if row["frequency"] <= 2:
            r.append("low purchase frequency")
        if row["avg_discount"] > 0.3:
            r.append("high reliance on discounts to purchase")
        if row["monetary"] < d["monetary"].median():
            r.append("below-median total spending")
        if not r:
            r.append("recent, frequent, and consistent purchase activity")
        return r

    # Row-wise .apply() here used to take ~50s on a 100k-row file; build the
    # reason lists with vectorized boolean masks instead, then only loop to
    # assemble each row's small list (cheap once the conditions are precomputed).
    monetary_median = d["monetary"].median()
    cond_recency = (d["recency"] > 90).to_numpy()
    cond_frequency = (d["frequency"] <= 2).to_numpy()
    cond_discount = (d["avg_discount"] > 0.3).to_numpy()
    cond_monetary = (d["monetary"] < monetary_median).to_numpy()
    recency_vals = d["recency"].to_numpy()

    reason_lists = []
    for i in range(len(d)):
        r = []
        if cond_recency[i]:
            r.append(f"{int(recency_vals[i])} days since last purchase")
        if cond_frequency[i]:
            r.append("low purchase frequency")
        if cond_discount[i]:
            r.append("high reliance on discounts to purchase")
        if cond_monetary[i]:
            r.append("below-median total spending")
        if not r:
            r.append("recent, frequent, and consistent purchase activity")
        reason_lists.append(r)

    d["risk_factors"] = reason_lists
    return d[["customer_id", "customer_name", "recency", "frequency", "monetary",
              "churn_probability", "risk_level", "risk_factors", "segment"]]