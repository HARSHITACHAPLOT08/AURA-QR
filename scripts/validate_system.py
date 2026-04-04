import requests
import time
import uuid

# Configuration
BACKEND_URL = "https://hattie-unbrushed-criminologically.ngrok-free.dev"
HEALTH_CHECK = f"{BACKEND_URL}/health"
ANALYZE_URL = f"{BACKEND_URL}/analyze"
HISTORY_URL = f"{BACKEND_URL}/history"

def validate_aura_system():
    print("🚀 Starting AURA End-to-End Validation...")

    # 1. Check Backend Health
    try:
        resp = requests.get(HEALTH_CHECK, timeout=5)
        if resp.status_code == 200:
            print("✅ Backend Health Check: OK")
        else:
            print(f"❌ Backend Health Check: FAILED (Status {resp.status_code})")
            return
    except Exception as e:
        print(f"❌ Backend Reachability: FAILED ({e})")
        return

    # 2. Simulate High-Risk Transaction (Payload from Mobile App logic)
    tx_id = f"VAL-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "transaction_id": tx_id,
        "amount": 4999.0,
        "merchant": "Suspect-Online-Shop",
        "location_risk": 0.95,
        "device_trust": 0.05,
        "txn_per_hour": 15,
        "source": "validation_script"
    }
    
    print(f"🧪 Simulating suspicious transaction {tx_id}...")
    try:
        resp = requests.post(ANALYZE_URL, json=payload, timeout=5)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Prediction received: Risk={result.get('risk_level')} (Score={result.get('fraud_probability')})")
        else:
            print(f"❌ Transaction Analysis: FAILED (Status {resp.status_code}: {resp.text})")
            return
    except Exception as e:
        print(f"❌ API POST: FAILED ({e})")
        return

    # 3. Verify Persistence in History
    print("🔎 Verifying persistence in history...")
    time.sleep(1)  # small delay for DB write
    try:
        resp = requests.get(HISTORY_URL, timeout=5)
        if resp.status_code == 200:
            history = resp.json()
            found = any(t.get('transaction_id') == tx_id for t in history)
            if found:
                print(f"✅ Transaction {tx_id} found in history! Persistence verified.")
            else:
                print(f"❌ Transaction {tx_id} NOT found in history.")
                return
        else:
            print(f"❌ History Check: FAILED (Status {resp.status_code})")
            return
    except Exception as e:
        print(f"❌ History Fetch: FAILED ({e})")
        return

    print("\n✨ ALL SYSTEMS WORKING")

if __name__ == "__main__":
    validate_aura_system()
