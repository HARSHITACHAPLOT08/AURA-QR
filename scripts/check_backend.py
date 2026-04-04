import requests

URL = 'https://hattie-unbrushed-criminologically.ngrok-free.dev/history'
try:
    r = requests.get(URL, timeout=5)
    print('status', r.status_code)
    try:
        data = r.json()
        print('type', type(data), 'len' if isinstance(data, list) else '', len(data) if isinstance(data, list) else '')
    except Exception as e:
        print('json error', e)
        print('text', r.text[:400])
except Exception as e:
    print('request failed:', e)
