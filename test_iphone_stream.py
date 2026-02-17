import cv2
import time

URL = "rtsp://192.168.1.16:8554/live.sdp"  # EJ: http://192.168.1.80:8080/video
# Si es RTSP, algo como: rtsp://192.168.1.80:8554/live

cap = cv2.VideoCapture(URL)  # OpenCV puede abrir streams por URL [1](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html)

print("isOpened:", cap.isOpened())
if not cap.isOpened():
    print("No se pudo abrir la cámara. Revisa URL / permisos de red local / WiFi.")
    raise SystemExit(1)

last_ok = time.time()
while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        # si se corta, espera un poco
        if time.time() - last_ok > 3:
            print("No llegan frames. ¿iPhone bloqueado? ¿URL correcta? ¿WiFi?")
        time.sleep(0.05)
        continue

    last_ok = time.time()
    cv2.imshow("iPhone Stream (pulsa q para salir)", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()