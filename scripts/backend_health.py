import requests

URL = 'https://hattie-unbrushed-criminologically.ngrok-free.dev/health'

try:
    r = requests.get(URL, timeout=5)
    print('status', r.status_code)
    try:
        print(r.json())
    except Exception:
        print('non-json response:')
        print(r.text[:400])
except Exception as e:
    print('error', e)
