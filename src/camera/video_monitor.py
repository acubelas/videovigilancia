"""
Clase `VideoMonitor` para detectar movimiento comparando fotogramas.

La clase usa OpenCV para conectarse a la cámara por defecto y compara
el fotograma actual con el anterior para detectar cambios basados en
un umbral de diferencia de píxeles.
"""

from typing import Optional, Callable
import time
import cv2
import numpy as np

import os
import sys

# Allow running this module both as a package and as a standalone script.
if __package__ is None or __package__ == "":
    # Insert the `src` package directory so `camera` can be imported directly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from camera.camera_manager import CameraManager
else:
    from .camera_manager import CameraManager


class VideoMonitor:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self.cam = CameraManager(camera_index)

    def start(self) -> bool:
        """Inicializa la cámara. Devuelve True si tuvo éxito."""
        return self.cam.init_camera()

    def stop(self) -> None:
        """Libera la cámara."""
        self.cam.release()

    def detect_motion(self, diff_threshold: int = 30, min_changed_pixels: int = 500, max_frames: Optional[int] = None, motion_cooldown_seconds: float = 2.0, on_motion: Optional[Callable[[], None]] = None) -> None:
        """
        Detecta movimiento comparando el fotograma actual con el anterior.

        Args:
            diff_threshold: Umbral (0-255) para clasificar píxeles como cambiados.
            min_changed_pixels: Número mínimo de píxeles cambiados para considerar que hay movimiento.
            max_frames: Número máximo de fotogramas a procesar (None = infinito).

        Si se detecta movimiento llama a `on_motion` si se proporciona; en caso
        contrario imprime 'Movimiento detectado' en consola.
        """
        if not self.cam.init_camera():
            print("No se pudo inicializar la cámara")
            return

        success, prev_frame = self.cam.get_frame()
        if not success or prev_frame is None:
            print("No se recibió el primer fotograma")
            self.cam.release()
            return

        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)

        frame_count = 0
        last_motion_time = 0.0
        try:
            while True:
                success, frame = self.cam.get_frame()
                if not success or frame is None:
                    break

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                # Diferencia absoluta y umbralización
                frame_delta = cv2.absdiff(prev_gray, gray)
                _, thresh = cv2.threshold(frame_delta, diff_threshold, 255, cv2.THRESH_BINARY)

                # Cuenta píxeles cambiados
                changed_pixels = int(np.count_nonzero(thresh))

                if changed_pixels >= min_changed_pixels:
                    now = time.time()
                    if now - last_motion_time >= motion_cooldown_seconds:
                        if on_motion is not None:
                            try:
                                on_motion()
                            except Exception:
                                # No propagamos errores del callback
                                pass
                        else:
                            print('Movimiento detectado')

                        last_motion_time = now

                prev_gray = gray

                frame_count += 1
                if max_frames is not None and frame_count >= max_frames:
                    break

        finally:
            self.cam.release()


if __name__ == '__main__':
    def _example_on_motion():
        print('Movimiento detectado (callback)')

    vm = VideoMonitor()
    if vm.start():
        # Ejecuta la detección durante 500 fotogramas como ejemplo
        vm.detect_motion(diff_threshold=30, min_changed_pixels=500, max_frames=500, on_motion=_example_on_motion)
    else:
        print('No se pudo iniciar la cámara')