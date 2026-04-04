import time
import requests
import sys
from pathlib import Path
# ensure project root is on sys.path so backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import get_recent_transactions

NGROK = "https://hattie-unbrushed-criminologically.ngrok-free.dev/transactions"

seen_db = set(r['transaction_id'] for r in get_recent_transactions(500))
print(f"Initial DB count: {len(seen_db)}")

try:
    r = requests.get(NGROK, timeout=5)
    data = r.json()
    if isinstance(data, dict):
        items = data.get('items') or data.get('transactions') or []
    else:
        items = data
    ids = [it.get('id') for it in items if isinstance(it, dict)]
    print(f"Backend initial count: {len(ids)}")
except Exception as e:
    print('Backend initial fetch error:', e)
    ids = []

seen_backend = set(ids)

# Poll for ~60 seconds (30 iterations x 2s)
for i in range(30):
    time.sleep(2)
    new_backend = []
    try:
        r = requests.get(NGROK, timeout=5)
        data = r.json()
        if isinstance(data, dict):
            items = data.get('items') or data.get('transactions') or []
        else:
            items = data
        ids = [it.get('id') for it in items if isinstance(it, dict)]
        for id in ids:
            if id not in seen_backend:
                new_backend.append(id)
                seen_backend.add(id)
    except Exception as e:
        print('Backend fetch error:', e)

    new_db = []
    try:
        rows = get_recent_transactions(200)
        for r in rows:
            tid = r.get('transaction_id')
            if tid and tid not in seen_db:
                new_db.append(tid)
                seen_db.add(tid)
    except Exception as e:
        print('DB fetch error:', e)

    if new_backend or new_db:
        print(f"[iter {i}] New backend IDs: {new_backend} | New DB IDs: {new_db}")
    else:
        print(f"[iter {i}] no new transactions (backend_count={len(seen_backend)}, db_count={len(seen_db)})")

print('Watcher finished.')
