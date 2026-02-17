import cv2

URL = "http://192.168.1.108:8080/videofeed"  # prueba primero /video

cap = cv2.VideoCapture(URL)  # OpenCV soporta streams por URL [5](https://camlytics.com/es/camera/ip_webcam_android)
print("isOpened:", cap.isOpened())

if not cap.isOpened():
    raise SystemExit("No se pudo abrir el stream. Prueba /videofeed o revisa el endpoint en la web.")

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        continue
    cv2.imshow("Android stream (q para salir)", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()