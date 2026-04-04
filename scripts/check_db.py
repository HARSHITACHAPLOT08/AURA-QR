from backend.database import get_recent_transactions
rows = get_recent_transactions(200)
ids = [r.get('transaction_id') for r in rows]
for i in ids[:30]:
    print(i)
print('contains fc5721a1?', 'fc5721a1-5446-4e86-8581-0d00cc795881' in ids)
