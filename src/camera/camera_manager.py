"""
Gestor de captura de video desde cámara local o streams (RTSP/HTTP MJPEG).
"""

import cv2
import logging
from typing import Optional, Tuple, Union

VideoSource = Union[int, str]


class CameraManager:
    def __init__(
        self,
        source: VideoSource = 0,
        camera_index: Optional[int] = None,   # compatibilidad con config antigua
        frame_width: int = 640,
        frame_height: int = 480,
        fps: int = 30,
        backend: Optional[int] = None,        # útil para webcam local (AVFOUNDATION/DSHOW)
    ):
        self.logger = logging.getLogger(__name__)

        if camera_index is not None:
            source = camera_index

        if isinstance(source, str) and source.strip().isdigit():
            source = int(source.strip())

        self.source = source
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.fps = fps
        self.backend = backend
        self.cap = None

    def init_camera(self) -> bool:
        try:
            # --- 1) URL (HTTP MJPEG / RTSP) ---
            if isinstance(self.source, str):
                # ✅ primero FFmpeg (mucho más estable para streams)
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)

                # Timeouts (si tu build los soporta; si no, se ignora sin romper)
                try:
                    self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 20000)  # 20s
                    self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 20000)  # 20s
                except Exception:
                    pass

                # Fallback: CAP_ANY
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.source)

            # --- 2) Cámara local por índice ---
            else:
                if self.backend is not None:
                    self.cap = cv2.VideoCapture(self.source, self.backend)
                else:
                    self.cap = cv2.VideoCapture(self.source)

            if not self.cap.isOpened():
                self.logger.error(f"No se pudo abrir la fuente de vídeo: {self.source!r}")
                return False

            # Propiedades (para streams IP puede no aplicar, pero no suele molestar)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

            self.logger.info(f"Fuente inicializada correctamente: {self.source!r}")
            return True

        except Exception as e:
            self.logger.error(f"Error al inicializar la fuente: {e}")
            return False

    def get_frame(self) -> Tuple[bool, Optional[object]]:
        if self.cap is None:
            self.logger.warning("La fuente de vídeo no está inicializada")
            return False, None
        return self.cap.read()

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            self.logger.info("Fuente de vídeo liberada")