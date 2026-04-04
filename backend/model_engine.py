"""
AURA — Model Engine
Loads trained models, runs inference, generates SHAP explanations.
"""
import json
import uuid
import numpy as np
import pandas as pd
import joblib
import shap
from pathlib import Path
from datetime import datetime

MODELS_DIR = Path(__file__).parent.parent / "models"
FEATURE_COLS = [
    "amount", "hour", "day_of_week", "merchant_cat",
    "location_risk", "device_trust", "past_fraud_ct",
    "velocity_1h", "dist_home_km", "card_age_days", "is_online",
]

# ── Lazy-loaded globals ─────────────────────────────────────────────
_xgb       = None
_iso       = None
_scaler    = None
_explainer = None


def _load_models():
    global _xgb, _iso, _scaler, _explainer
    if _xgb is None:
        _xgb       = joblib.load(MODELS_DIR / "xgboost_model.pkl")
        _iso       = joblib.load(MODELS_DIR / "isolation_forest.pkl")
        _scaler    = joblib.load(MODELS_DIR / "scaler.pkl")
        _explainer = joblib.load(MODELS_DIR / "shap_explainer.pkl")


def models_ready() -> bool:
    return (MODELS_DIR / "xgboost_model.pkl").exists()


def risk_level(prob: float) -> str:
    if prob < 0.35:
        return "Low"
    elif prob < 0.65:
        return "Medium"
    return "High"


def predict(transaction: dict) -> dict:
    """
    Parameters
    ----------
    transaction : dict with keys matching FEATURE_COLS

    Returns
    -------
    Full prediction dict ready for DB + UI.
    """
    _load_models()

    df = pd.DataFrame([transaction])[FEATURE_COLS]
    X_scaled = _scaler.transform(df)
    X_df     = pd.DataFrame(X_scaled, columns=FEATURE_COLS)

    # XGBoost probability
    prob = float(_xgb.predict_proba(X_df)[0, 1])

    # Isolation Forest anomaly score (scaled -1=anomaly → 0-1)
    raw_score    = float(_iso.decision_function(X_df)[0])
    anomaly_score = float(np.clip(1 - (raw_score + 0.5), 0, 1))

    # Blend: 80 % XGB + 20 % IF
    blended_prob = min(1.0, 0.80 * prob + 0.20 * anomaly_score)

    level    = risk_level(blended_prob)
    is_fraud = blended_prob >= 0.5

    # SHAP explanation — handle both old (list) and new (2D array) SHAP API
    shap_output = _explainer.shap_values(X_df)
    if isinstance(shap_output, list):
        row_shap = shap_output[1][0]   # positive class, first row
    else:
        row_shap = shap_output[0]      # 2D array, first row
    shap_series = pd.Series(row_shap, index=FEATURE_COLS)
    top_features = shap_series.abs().sort_values(ascending=False).head(6)
    top_dict = {
        feat: {"shap": float(shap_series[feat]), "value": float(transaction[feat])}
        for feat in top_features.index
    }

    return {
        "transaction_id":   transaction.get("transaction_id", f"TXN-{uuid.uuid4().hex[:8].upper()}"),
        "amount":           float(transaction["amount"]),
        "hour":             int(transaction["hour"]),
        "day_of_week":      int(transaction["day_of_week"]),
        "merchant_cat":     int(transaction["merchant_cat"]),
        "location_risk":    float(transaction["location_risk"]),
        "device_trust":     float(transaction["device_trust"]),
        "past_fraud_ct":    int(transaction["past_fraud_ct"]),
        "velocity_1h":      int(transaction["velocity_1h"]),
        "dist_home_km":     float(transaction["dist_home_km"]),
        "card_age_days":    int(transaction["card_age_days"]),
        "is_online":        bool(transaction["is_online"]),
        "fraud_probability":round(blended_prob, 4),
        "risk_level":       level,
        "is_fraud":         is_fraud,
        "anomaly_score":    round(anomaly_score, 4),
        "top_features":     json.dumps(top_dict),
        "timestamp":        datetime.utcnow(),
        "source":           transaction.get("source", "manual"),
        "merchant":         transaction.get("merchant"),
    }
