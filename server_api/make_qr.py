import json
import requests
import qrcode
from pathlib import Path

API_BASE = "http://127.0.0.1:8080"
PUBLIC_URL = "http://100.88.172.7:8080"

def main():
    resp = requests.post(
        f"{API_BASE}/pairing/request",
        json={"method": "qr", "serverUrl": PUBLIC_URL},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()

    pairing_id = data["pairingId"]
    otp = data["otp"]

    payload = {"serverUrl": PUBLIC_URL, "pairingId": pairing_id}
    qr_text = json.dumps(payload)

    out_png = Path("/tmp/pairing_qr.png")
    out_json = Path("/tmp/pairing_payload.json")

    img = qrcode.make(qr_text)
    img.save(out_png)
    out_json.write_text(qr_text, encoding="utf-8")

    print("✅ QR:", out_png)
    print("✅ JSON:", out_json)
    print("pairingId:", pairing_id)
    print("OTP:", otp)
    print("Contenido QR:", qr_text)

if __name__ == "__main__":
    main()