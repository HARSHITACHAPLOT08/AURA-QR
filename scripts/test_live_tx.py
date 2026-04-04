import requests
import json
import time
import uuid

NGROK_URL = "https://hattie-unbrushed-criminologically.ngrok-free.dev"
HEADERS = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}

def test_live_transaction():
    try:
        # 1. Create a dummy mobile transaction
        tx_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "amount": 250.0,
            "merchant": "TEST_MERCHANT_ANTIGRAVITY",
            "location_risk": 0.1,
            "device_trust": 0.9,
            "txn_per_hour": 1,
            "source": "mobile",
            "transaction_id": tx_id
        }
        
        print(f"Sending test transaction {tx_id} to {NGROK_URL}/analyze...")
        resp = requests.post(f"{NGROK_URL}/analyze", headers=HEADERS, json=payload, timeout=10)
        print(f"POST Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Transaction processed successfully.")
            
            # 2. Wait a moment for DB sync
            time.sleep(2)
            
            # 3. Check history to confirm it's in the system
            print(f"Checking {NGROK_URL}/history...")
            h_resp = requests.get(f"{NGROK_URL}/history", headers=HEADERS, timeout=10)
            if h_resp.status_code == 200:
                txs = h_resp.json()
                found = any(tx.get('transaction_id') == tx_id for tx in txs)
                if found:
                    print(f"SUCCESS: Transaction {tx_id} found in history!")
                else:
                    print(f"FAILED: Transaction {tx_id} NOT found in history.")
            else:
                print(f"History Check Failed: {h_resp.status_code}")
        else:
            print(f"POST Failed: {resp.text}")
            
    except Exception as e:
        print(f"Test Failed: {e}")

if __name__ == "__main__":
    test_live_transaction()
