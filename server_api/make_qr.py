import json
import requests
import qrcode

API_BASE = "http://127.0.0.1:8080"        # el servidor visto desde el Mac
PUBLIC_URL = "http://100.88.172.7:8080"   # el servidor visto desde el iPhone por Tailscale

def main():
    # 1) pedir pairingCode
    resp = requests.post(f"{API_BASE}/pairing/code", timeout=10)
    resp.raise_for_status()
    code = resp.json()["pairingCode"]

    # 2) JSON que irá dentro del QR
    payload = {"serverUrl": PUBLIC_URL, "pairingCode": code}
    text = json.dumps(payload)

    # 3) generar QR como PNG
    img = qrcode.make(text)
    img.save("pairing_qr.png")

    print("✅ QR generado: pairing_qr.png")
    print("Contenido QR:", text)

if __name__ == "__main__":
    main()