import cv2

def discover_local_cameras(max_index: int = 10):
    found = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # Windows
        if not cap.isOpened():
            cap.release()
            continue

        ok, frame = cap.read()
        cap.release()

        if ok and frame is not None:
            found.append({"type": "local", "id": f"local-{idx}", "name": f"Webcam {idx}", "uri": idx})
    return found