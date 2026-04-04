import time
import requests
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import get_recent_transactions

NGROK_BASE = "https://hattie-unbrushed-criminologically.ngrok-free.dev"
TRANSACTIONS = NGROK_BASE + "/transactions"
ANALYZE = NGROK_BASE + "/analyze"
LOGFILE = Path(__file__).resolve().parent.parent / 'logs' / 'continuous_watcher.log'
LOGFILE.parent.mkdir(exist_ok=True)

seen_db = set(r['transaction_id'] for r in get_recent_transactions(1000))
seen_backend = set()

def now():
    return datetime.utcnow().isoformat()

def log(msg):
    ts = now()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOGFILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

log(f"Starting continuous watcher. Initial DB count: {len(seen_db)}")

while True:
    try:
        # Poll transactions
        try:
            r = requests.get(TRANSACTIONS, timeout=6)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                items = data.get('items') or data.get('transactions') or []
            else:
                items = data
            ids = [it.get('id') for it in items if isinstance(it, dict) and it.get('id')]
            for id in ids:
                if id not in seen_backend:
                    log(f"New backend transaction ID observed: {id}")
                    seen_backend.add(id)
        except Exception as e:
            log(f"Error polling /transactions: {repr(e)}")

        # Poll analyze endpoint (GET) to detect whether it's reachable
        try:
            r2 = requests.get(ANALYZE, timeout=6)
            log(f"GET /analyze status={r2.status_code} len={len(r2.text) if r2.text else 0}")
        except Exception as e:
            log(f"Error polling /analyze: {repr(e)}")

        # Check local DB for new rows
        try:
            rows = get_recent_transactions(200)
            new_db = [r['transaction_id'] for r in rows if r.get('transaction_id') and r['transaction_id'] not in seen_db]
            for tid in new_db:
                log(f"New DB row: {tid}")
                seen_db.add(tid)
        except Exception as e:
            log(f"Error reading DB: {repr(e)}")

    except KeyboardInterrupt:
        log("Watcher terminated by KeyboardInterrupt")
        break
    time.sleep(2)
