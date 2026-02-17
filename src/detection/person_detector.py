import time
import cv2
from ultralytics import YOLO

class PersonDetector:
    """
    Detector de personas basado en IA (YOLOv8) optimizado para CPU.
    """

    def __init__(
        self,
        model_path: str = "models/yolov8n.pt",
                 confidence_threshold=0.35,
                 min_area=1500,
                 min_area_ratio=0.002,   # NUEVO
                 min_persistence_frames=3,
                 cooldown_seconds=30):
        # Cargar modelo LOCAL (sin descargas)
        self.model = YOLO(model_path)

        self.confidence_threshold = confidence_threshold
        self.min_area = min_area
        self.min_area_ratio = min_area_ratio
        self.min_persistence_frames = min_persistence_frames
        self.cooldown_seconds = cooldown_seconds

        self._person_frames = 0
        self._last_alert_time = 0.0

    def detect(self, frame):
        """
        Devuelve (person_confirmed, annotated_frame)
        """
        # ✅ 1) Asegurar que annotated_frame siempre existe
        annotated_frame = frame.copy()

        # ✅ 2) Seguridad por si llega frame inválido
        if frame is None or frame.size == 0:
            cv2.putText(
                annotated_frame,
                "Frame invalido",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )
            return False, annotated_frame

        # ✅ 3) Ejecutar YOLO dentro de try para que nunca rompa el bucle
        try:
            results = self.model(frame, classes=[0], verbose=False)
        except Exception as e:
            cv2.putText(
                annotated_frame,
                f"YOLO error: {e}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2
            )
            return False, annotated_frame

        detected = False

        # ✅ DEBUG: cuántas detecciones devuelve YOLO (antes de tus filtros)
        num_boxes = 0
        best_conf = 0.0
        if results and results[0].boxes is not None and len(results[0].boxes) > 0:
            num_boxes = len(results[0].boxes)
            # max confidence del tensor de conf
            best_conf = float(results[0].boxes.conf.max().item())

        cv2.putText(
            annotated_frame,
            f"YOLO boxes: {num_boxes} best_conf: {best_conf:.2f}",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2
        )

        # --- Tu lógica de filtros/dibujo (tal como la tienes) ---
        for box in results[0].boxes:
            conf = float(box.conf[0])
            if conf < self.confidence_threshold:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            w = x2 - x1
            h = y2 - y1
            area = w * h

            if area < self.min_area:
                continue

            aspect_ratio = h / max(w, 1)
            if not 1.6 <= aspect_ratio <= 4.5:
                continue

            detected = True

            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                annotated_frame,
                f"PERSON {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )
            break

        # Persistencia
        if detected:
            self._person_frames += 1
        else:
            self._person_frames = 0

        frames_now = self._person_frames

        confirmed = False
        if self._person_frames >= self.min_persistence_frames:
            now = time.time()
            if now - self._last_alert_time >= self.cooldown_seconds:
                self._last_alert_time = now
                confirmed = True
                # guardar antes de reset
                frames_now = self._person_frames
                self._person_frames = 0

        cv2.putText(
            annotated_frame,
            f"frames_persona: {frames_now}",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )

        return confirmed, annotated_frame