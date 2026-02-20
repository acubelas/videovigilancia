import time
import cv2
import numpy as np
from ultralytics import YOLO


class PersonDetector:
    """
    Detector de personas basado en IA (YOLOv8) optimizado para CPU
    con mejoras automáticas para visión nocturna.
    """

    def __init__(
        
        self,
        model_path: str = "models/yolov8n.pt",
        confidence_threshold=0.35,
        min_area=1500,
        min_area_ratio=0.002,
        min_persistence_frames=3,
        cooldown_seconds=30,
    ):
        self.last_detected_type = None
        # Modelo YOLO local
        self.model = YOLO(model_path)
        self.last_brightness = None
        self.base_confidence = confidence_threshold
        self.min_area = min_area
        self.min_area_ratio = min_area_ratio
        self.min_persistence_frames = min_persistence_frames
        self.cooldown_seconds = cooldown_seconds

        # Clases YOLO relevantes (personas + vehículos)
        self.allowed_classes = {
            0: "PERSONA",
            2: "COCHE",
            3: "MOTO",
            5: "AUTOBÚS",
            7: "CAMIÓN",
        }

        self.last_detected_type = None



        self._person_frames = 0
        self._last_alert_time = 0.0

    # ------------------------------------------------------------------
    # 🔧 UTILIDADES VISIÓN NOCTURNA
    # ------------------------------------------------------------------

    @staticmethod
    def _measure_brightness(frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, _, _ = cv2.split(lab)
        return float(l.mean())

    @staticmethod
    def _apply_clahe(frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

    @staticmethod
    def _adjust_gamma(frame, gamma):
        inv_gamma = 1.0 / gamma
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in range(256)]
        ).astype("uint8")
        return cv2.LUT(frame, table)

    # ------------------------------------------------------------------

    def detect(self, frame):
        """
        Devuelve (person_confirmed, annotated_frame)
        """
        annotated_frame = frame.copy() if frame is not None else frame

        if frame is None or frame.size == 0:
            if annotated_frame is not None:
                cv2.putText(
                    annotated_frame,
                    "Frame invalido",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                )
            return False, annotated_frame

        # ------------------------------------------------------------------
        # 🌙 MEJORA AUTOMÁTICA PARA IMÁGENES OSCURAS
        # ------------------------------------------------------------------
        brightness = self._measure_brightness(frame)
        self.last_brightness = brightness
        frame_proc = frame

        if brightness < 70:
            frame_proc = self._apply_clahe(frame_proc)

        if brightness < 60:
            gamma = 1.8 if brightness > 50 else 2.2
            frame_proc = self._adjust_gamma(frame_proc, gamma)

        if brightness < 55:
            frame_proc = cv2.fastNlMeansDenoisingColored(
                frame_proc, None, 5, 5, 7, 21
            )

        # Ajuste dinámico de confianza
        confidence = self.base_confidence
        if brightness < 50:
            confidence -= 0.15
        elif brightness < 65:
            confidence -= 0.10

        confidence = max(0.15, min(confidence, 0.6))
        # ------------------------------------------------------------------

        try:
            results = self.model(
                frame_proc,
                classes=list(self.allowed_classes.keys()),
                conf=confidence,
                verbose=False,
            )
        except Exception as e:
            cv2.putText(
                annotated_frame,
                f"YOLO error: {e}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )
            return False, annotated_frame

        detected = False
        num_boxes = 0
        best_conf = 0.0

        if results and results[0].boxes is not None and len(results[0].boxes) > 0:
            num_boxes = len(results[0].boxes)
            best_conf = float(results[0].boxes.conf.max().item())

        cv2.putText(
            annotated_frame,
            f"YOLO boxes: {num_boxes} best_conf: {best_conf:.2f} "
            f"brillo: {brightness:.0f} conf:{confidence:.2f}",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 0),
            2,
        )

        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            label = self.allowed_classes.get(cls_id, "OBJETO")
            conf = float(box.conf[0])
            if conf < confidence:
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

            cv2.rectangle(
                annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2
            )
            cv2.putText(
                annotated_frame,
                f"{label} {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            break

        if detected:
            self._person_frames += 1
            self.last_detected_type = label
        else:
            self._person_frames = 0

        frames_now = self._person_frames
        confirmed = False

        if self._person_frames >= self.min_persistence_frames:
            now = time.time()
            if now - self._last_alert_time >= self.cooldown_seconds:
                self._last_alert_time = now
                confirmed = True
                frames_now = self._person_frames
                self._person_frames = 0

        cv2.putText(
            annotated_frame,
            f"frames_persona: {frames_now}",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )

        return confirmed, annotated_frame