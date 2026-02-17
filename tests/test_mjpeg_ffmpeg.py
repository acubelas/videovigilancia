import cv2
import time

url = "http://192.168.1.108:8080/video"

cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

# (Opcional) subir timeouts si tu OpenCV los soporta
cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 20000)  # 20s
cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 20000)  # 20s

print("isOpened:", cap.isOpened())

t0 = time.time()
ok, frame = cap.read()
print("read ok:", ok, "elapsed:", round(time.time() - t0, 2), "s")

if ok:
    cv2.imshow("MJPEG", frame)
    cv2.waitKey(0)

cap.release()
cv2.destroyAllWindows()