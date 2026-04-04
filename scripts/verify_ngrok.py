import requests
import json

NGROK_URL = "https://hattie-unbrushed-criminologically.ngrok-free.dev"
HEADERS = {"ngrok-skip-browser-warning": "true"}

def verify_connection():
    try:
        print(f"Checking {NGROK_URL}/health...")
        resp = requests.get(f"{NGROK_URL}/health", headers=HEADERS, timeout=5)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.json()}")
        
        print(f"\nChecking {NGROK_URL}/history...")
        resp = requests.get(f"{NGROK_URL}/history", headers=HEADERS, timeout=5)
        print(f"Status: {resp.status_code}")
        txs = resp.json()
        print(f"Retrieved {len(txs)} transactions.")
        if txs:
            print("Latest Transaction ID:", txs[0].get('transaction_id'))
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    verify_connection()
