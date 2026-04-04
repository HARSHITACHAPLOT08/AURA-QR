"""
AURA — FastAPI Backend
Endpoints: /predict  /history  /stats  /stream-next
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import uuid

from backend.model_engine import predict, models_ready
from backend.database     import save_transaction, get_recent_transactions, get_stats
from backend.alert_system import get_recommendations
from ml.generate_synthetic import generate_transactions

app = FastAPI(
    title="AURA Fraud Detection API",
    description="AI-Powered Real-Time Fraud Detection & Financial Guardian System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Synthetic pool for streaming
_stream_pool = None


def _get_stream_pool():
    global _stream_pool
    if _stream_pool is None:
        df = generate_transactions(n_samples=500)
        _stream_pool = df.to_dict(orient="records")
    return _stream_pool


# ── Schemas ─────────────────────────────────────────────────────────
class TransactionInput(BaseModel):
    amount:        float = Field(..., gt=0)
    hour:          int   = Field(..., ge=0, le=23)
    day_of_week:   int   = Field(..., ge=0, le=6)
    merchant_cat:  int   = Field(..., ge=1, le=5)
    location_risk: float = Field(..., ge=0, le=1)
    device_trust:  float = Field(..., ge=0, le=1)
    past_fraud_ct: int   = Field(..., ge=0)
    velocity_1h:   int   = Field(..., ge=0)
    dist_home_km:  float = Field(..., ge=0)
    card_age_days: int   = Field(..., ge=0)
    is_online:     bool  = False
    source:        str   = "manual"


# ── Routes ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "models_ready": models_ready()}


@app.post("/predict")
def predict_fraud(tx: TransactionInput):
    if not models_ready():
        raise HTTPException(503, detail="Models not trained yet. Run ml/train_model.py first.")
    data = tx.model_dump()
    data["transaction_id"] = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    result = predict(data)
    save_transaction(result)
    recs = get_recommendations(result["risk_level"], data)
    return {**result, "recommendations": recs}


@app.get("/stream-next")
def stream_next():
    """Return one random transaction from the synthetic pool + run inference."""
    if not models_ready():
        raise HTTPException(503, detail="Models not trained yet.")
    pool = _get_stream_pool()
    import random
    tx   = random.choice(pool)
    tx["transaction_id"] = f"STR-{uuid.uuid4().hex[:8].upper()}"
    tx["source"] = "stream"
    result = predict(tx)
    save_transaction(result)
    return result


@app.get("/history")
@app.get("/transactions")
def history(limit: int = 50):
    return get_recent_transactions(limit)


@app.get("/stats")
def stats():
    return get_stats()


@app.get("/analyze")
def analyze_get():
    # Log that a GET was received (mobile may be calling GET accidentally)
    print("[ANALYZE] GET received - endpoint expects POST with JSON payload")
    return {"detail": "This endpoint accepts POST with JSON payload. Use POST to submit transaction data."}


@app.post("/analyze")
async def analyze_post(request: Request):
    """Accept free-form transaction JSON from mobile apps, run prediction, save and return result.

    Expected JSON keys (partial): amount, merchant, location_risk, device_trust, txn_per_hour
    """
    try:
        body = await request.json()
    except Exception as e:
        print(f"[ANALYZE] Failed to parse JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Log the incoming payload for debugging
    print("[ANALYZE] Received payload:", body)

    if not models_ready():
        print("[ANALYZE] Models not ready")
        raise HTTPException(503, detail="Models not trained yet.")

    # Map incoming keys into our internal transaction dict
    tx = {}
    tx['amount'] = body.get('amount')
    # map merchant -> merchant_cat if provided; otherwise keep raw merchant name
    tx['merchant'] = body.get('merchant')
    tx['merchant_cat'] = body.get('merchant_cat') or None
    tx['location_risk'] = body.get('location_risk') or body.get('locationRisk') or 0.0
    tx['device_trust'] = body.get('device_trust') or body.get('deviceTrust') or 0.0
    tx['velocity_1h'] = body.get('txn_per_hour') or body.get('txnPerHour') or body.get('velocity_1h') or 0
    tx['hour'] = body.get('hour')
    tx['day_of_week'] = body.get('day_of_week')
    tx['dist_home_km'] = body.get('dist_home_km')
    tx['card_age_days'] = body.get('card_age_days')
    tx['is_online'] = body.get('is_online', False)
    tx['source'] = body.get('source', 'mobile')
    tx['transaction_id'] = body.get('transaction_id') or f"MOB-{uuid.uuid4().hex[:8].upper()}"

    # Sanitize / validate inputs before sending to model
    try:
        # Coerce numeric fields and apply sensible defaults
        from datetime import datetime as _dt
        tx['amount'] = float(tx.get('amount', 0.0))
        _hour = tx.get('hour')
        tx['hour'] = int(_hour) if _hour is not None else int(_dt.utcnow().hour)
        _dow = tx.get('day_of_week')
        tx['day_of_week'] = int(_dow) if _dow is not None else int(_dt.utcnow().weekday())
        # merchant_cat may be provided as name or id; default to 3 (Online)
        mc = tx.get('merchant_cat')
        try:
            tx['merchant_cat'] = int(mc) if mc is not None else 3
        except Exception:
            tx['merchant_cat'] = 3

        # location_risk/device_trust sometimes sent as 0-100 percentages; normalize to 0-1
        def _norm_prob(v):
            try:
                vv = float(v)
            except Exception:
                return 0.0
            if vv > 1 and vv <= 100:
                return max(0.0, min(1.0, vv / 100.0))
            return max(0.0, min(1.0, vv))

        tx['location_risk'] = _norm_prob(tx.get('location_risk', 0.0))
        tx['device_trust'] = _norm_prob(tx.get('device_trust', 0.0))

        _pfc = tx.get('past_fraud_ct')
        tx['past_fraud_ct'] = int(_pfc) if _pfc is not None else 0
        _v1 = tx.get('velocity_1h') or tx.get('txn_per_hour')
        tx['velocity_1h'] = int(_v1) if _v1 is not None else 0
        _dist = tx.get('dist_home_km')
        tx['dist_home_km'] = float(_dist) if _dist is not None else 0.0
        _cad = tx.get('card_age_days')
        tx['card_age_days'] = int(_cad) if _cad is not None else 365
        _online = tx.get('is_online')
        tx['is_online'] = bool(_online) if _online is not None else True
    except Exception as e:
        print(f"[ANALYZE] Input sanitization error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid input: {e}")

    # Run prediction
    try:
        result = predict(tx)
    except Exception as e:
        print(f"[ANALYZE] Prediction error: {e}")
        raise HTTPException(status_code=500, detail="Prediction failed")

    # Persist the result and confirm
    try:
        saved = save_transaction(result)
        print(f"[ANALYZE] Saved transaction id={saved.transaction_id} db_id={saved.id}")
    except Exception as e:
        print(f"[ANALYZE] DB save error: {e}")
        # still return result but inform client
        return {**result, "saved": False, "error": str(e)}

    # Return the prediction + basic info
    try:
        recs = get_recommendations(result.get('risk_level'), tx)
    except Exception:
        recs = {}

    return {**result, "recommendations": recs, "saved": True}


if __name__ == "__main__":
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)
