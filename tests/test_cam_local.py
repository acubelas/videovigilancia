import cv2

# En macOS suele ser más estable usar el backend AVFoundation explícitamente
# y probar varios índices de cámara para evitar coger la Continuity Camera.
BACKEND = cv2.CAP_AVFOUNDATION  # Alternativas: cv2.CAP_QT, cv2.CAP_AVFOUNDATION

def try_cam(idx):
    cap = cv2.VideoCapture(idx, BACKEND)
    ok = cap.isOpened()
    print(f"Cam {idx} abierta: {ok}")
    if ok:
        ret, frame = cap.read()
        print(f"  Frame leído: {ret}")
        if ret:
            h, w = frame.shape[:2]
            print(f"  Resolución: {w}x{h}")
            cv2.imshow(f"Cámara {idx}", frame)
            print("Pulsa 'q' para cerrar la ventana…")
            while True:
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        cap.release()
        cv2.destroyAllWindows()

for i in range(0, 4):
    try_cam(i)
    