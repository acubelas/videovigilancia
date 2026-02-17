import requests

url = "http://192.168.1.108:8080/"
try:
    r = requests.get(url, timeout=5)
    print("HTTP status:", r.status_code)
    print("Server:", r.headers.get("Server"))
    print("Content-Type:", r.headers.get("Content-Type"))
    print("Bytes:", len(r.content))
except Exception as e:
    print("ERROR:", e)
