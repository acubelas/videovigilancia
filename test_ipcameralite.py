import cv2
import time

URL = "http://192.168.1.16:8081/video"

cap = cv2.VideoCapture(URL)  # OpenCV soporta streams por URL [3](https://docs.netskope.com/en/netskope-client-interoperability/)
print("isOpened:", cap.isOpened())

if not cap.isOpened():
    raise SystemExit("No se pudo abrir el stream MJPEG. Revisa puerto 8081, permisos iPhone, app abierta.")

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        time.sleep(0.01)
        continue

    cv2.imshow("iPhone - IP Camera Lite (pulsa q para salir)", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()