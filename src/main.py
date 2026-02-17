"""
Aplicación principal de videovigilancia (Opción 2)
- Selección de fuente por CLI: índice (0) o URL (http/rtsp).
- --drop-frames para reducir latencia en streams (MJPEG/RTSP) saltando frames antiguos.
"""

import sys
import cv2
import logging
import time
import argparse
import inspect
from pathlib import Path

# Agregar el directorio src al path (para poder importar config.py y módulos)
sys.path.insert(0, str(Path(__file__).parent))

from camera.camera_manager import CameraManager
from detection.person_detector import PersonDetector
from alerts.telegram_alert import TelegramAlert
from utils.logger import setup_logger
from config import CAMERA_CONFIG, TELEGRAM_CONFIG, RECORDING_CONFIG


# -----------------------------
# CLI / Fuente de vídeo (Opción 2)
# -----------------------------
def parse_source(value: str):
    """Convierte --source en int si es dígito; si no, lo trata como URL."""
    v = value.strip()
    return int(v) if v.isdigit() else v


def default_backend_for_source(source):
    """Backend recomendado cuando la fuente es índice (webcam local)."""
    if isinstance(source, int):
        if sys.platform == "darwin":
            return cv2.CAP_AVFOUNDATION
        elif sys.platform.startswith("win"):
            return cv2.CAP_DSHOW
    return None


def build_args():
    p = argparse.ArgumentParser(description="Videovigilancia - detección y alertas (Opción 2)")
    p.add_argument(
        "--source",
        default="0",
        help="Índice de cámara (0) o URL (rtsp://..., http://.../video)"
    )
    p.add_argument("--width", type=int, default=None, help="Ancho deseado (cámara local normalmente)")
    p.add_argument("--height", type=int, default=None, help="Alto deseado (cámara local normalmente)")
    p.add_argument("--no-gui", action="store_true", help="No mostrar ventana OpenCV (modo headless)")
    p.add_argument("--duration", type=int, default=0, help="Segundos para auto-salida (0 = sin límite)")

    # ✅ Reducción de latencia (muy útil en MJPEG/HTTP)
    p.add_argument(
        "--drop-frames",
        type=int,
        default=0,
        help="Saltar N frames antes de leer (reduce latencia en streams). Ej: 5..15"
    )

    return p.parse_args()


def filter_kwargs_for_callable(callable_obj, kwargs: dict) -> dict:
    """Filtra kwargs dejando solo las claves aceptadas por callable_obj."""
    try:
        sig = inspect.signature(callable_obj)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        return kwargs


class VideoSurveillanceApp:
    def __init__(self, source=0, width=None, height=None, show_gui=True, duration=0, drop_frames=0):
        self.logger = setup_logger(__name__, logging.INFO)
        self.logger.info("=" * 60)
        self.logger.info("Iniciando aplicación de videovigilancia (Opción 2)")
        self.logger.info("=" * 60)

        self.source = source
        self.width = width
        self.height = height
        self.show_gui = show_gui
        self.duration = int(duration or 0)

        # ✅ drop frames para streams (reduce latencia)
        self.drop_frames = max(0, int(drop_frames or 0))

        self.camera = None
        self.telegram_alert = None
        self.video_writer = None

        self.person_detector = PersonDetector(
            confidence_threshold=0.35,
            min_area=1500,
            min_persistence_frames=3,
            cooldown_seconds=30
        )

        self._initialize_components()

    def _initialize_components(self):
        cam_cfg = dict(CAMERA_CONFIG)

        # Si source es índice -> camera_index; si es URL -> source
        if isinstance(self.source, int):
            cam_cfg["camera_index"] = self.source
            cam_cfg.pop("source", None)
        else:
            cam_cfg["source"] = self.source
            cam_cfg.pop("camera_index", None)

        # Backend recomendado para webcams locales
        backend = default_backend_for_source(self.source)
        if backend is not None:
            cam_cfg["backend"] = backend

        # width/height por CLI (si vienen)
        if self.width is not None:
            cam_cfg["frame_width"] = self.width
            cam_cfg["width"] = self.width
        if self.height is not None:
            cam_cfg["frame_height"] = self.height
            cam_cfg["height"] = self.height

        cam_cfg_filtered = filter_kwargs_for_callable(CameraManager.__init__, cam_cfg)

        self.logger.info(f"Inicializando cámara/fuente con config: {cam_cfg_filtered}")

        self.camera = CameraManager(**cam_cfg_filtered)
        ok = self.camera.init_camera()
        cap_is_none = getattr(self.camera, "cap", None) is None
        self.logger.info(f"init_camera() -> {ok} | cap is None -> {cap_is_none}")

        if not ok or cap_is_none:
            self.logger.error("No se pudo inicializar la cámara/fuente de vídeo")
            sys.exit(1)

        # Telegram (opcional)
        if TELEGRAM_CONFIG.get("enabled"):
            self.telegram_alert = TelegramAlert(
                TELEGRAM_CONFIG["bot_token"],
                TELEGRAM_CONFIG["chat_id"]
            )
            self.logger.info("Alertas por Telegram habilitadas")

        # Grabación (opcional)
        if RECORDING_CONFIG.get("enabled"):
            self._initialize_video_writer()

    def _initialize_video_writer(self):
        try:
            success, frame = self.camera.get_frame()
            if success and frame is not None:
                h, w = frame.shape[:2]
                codec = cv2.VideoWriter_fourcc(*RECORDING_CONFIG["codec"])
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_dir = Path(RECORDING_CONFIG["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"surveillance_{timestamp}.mp4"

                self.video_writer = cv2.VideoWriter(
                    str(output_path),
                    codec,
                    RECORDING_CONFIG["fps"],
                    (w, h)
                )
                self.logger.info(f"Grabación iniciada: {output_path}")
        except Exception as e:
            self.logger.error(f"Error al inicializar grabación: {e}")

    def _send_alert(self, message: str, frame=None):
        """Envía alerta Telegram con foto (si frame no es None)."""
        self.logger.warning(f"🚨 ALERTA: {message}")

        photo_path = None
        if frame is not None:
            try:
                Path("logs").mkdir(exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                photo_path = Path("logs") / f"alert_{timestamp}.jpg"
                ok = cv2.imwrite(str(photo_path), frame)
                if not ok:
                    self.logger.error("cv2.imwrite no pudo guardar la imagen")
                    photo_path = None
            except Exception as e:
                self.logger.error(f"Error al guardar foto: {e}")
                photo_path = None

        if TELEGRAM_CONFIG.get("enabled") and self.telegram_alert:
            self.telegram_alert.send_alert_async(message, str(photo_path) if photo_path else None)

    def _read_frame_low_latency(self):
        """
        Lee frame intentando reducir latencia para streams:
        - si source es URL y drop_frames>0, hace grab() N veces para saltar cola.
        """
        cap = getattr(self.camera, "cap", None)

        if isinstance(self.source, str) and self.drop_frames > 0 and cap is not None:
            # Saltar frames antiguos (reduce latencia)
            # Ajusta drop_frames (5..15 típico para bajar ~3s)
            for _ in range(self.drop_frames):
                cap.grab()

        return self.camera.get_frame()

    def run(self):
        try:
            self.logger.info("Iniciando captura de video...")
            frame_count = 0
            start_time = time.time()

            if isinstance(self.source, str) and self.drop_frames > 0:
                self.logger.info(f"Modo baja latencia activado: drop_frames={self.drop_frames}")

            while True:
                # Auto-salida por duración
                if self.duration > 0 and (time.time() - start_time) >= self.duration:
                    self.logger.info(f"Duración alcanzada ({self.duration}s). Saliendo...")
                    break

                success, frame = self._read_frame_low_latency()
                if not success or frame is None:
                    self.logger.error("Error al capturar frame")
                    break

                frame_count += 1

                # Detectar personas
                person_detected, annotated_frame = self.person_detector.detect(frame)

                if person_detected:
                    message = (
                        "🚨 PERSONA DETECTADA\n"
                        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    # Enviar frame original (si prefieres anotado: annotated_frame)
                    self._send_alert(message, frame)

                # Grabar (opcional)
                if self.video_writer and RECORDING_CONFIG.get("enabled"):
                    self.video_writer.write(annotated_frame)

                # Overlay simple
                info_text = f"Frames: {frame_count}"
                cv2.putText(
                    annotated_frame,
                    info_text,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

                # Mostrar ventana
                if self.show_gui:
                    cv2.imshow("Videovigilancia - Detección", annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self.logger.info("Usuario ha solicitado salida")
                        break

        except KeyboardInterrupt:
            self.logger.info("Interrupción por teclado (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        self.logger.info("Limpiando recursos...")

        if self.camera:
            self.camera.release()

        if self.video_writer:
            self.video_writer.release()

        if self.show_gui:
            cv2.destroyAllWindows()

        self.logger.info("Recursos liberados correctamente")
        self.logger.info("=" * 60)
        self.logger.info("Aplicación finalizada")
        self.logger.info("=" * 60)


def main():
    args = build_args()
    source = parse_source(args.source)

    app = VideoSurveillanceApp(
        source=source,
        width=args.width,
        height=args.height,
        show_gui=(not args.no_gui),
        duration=args.duration,
        drop_frames=args.drop_frames
    )
    app.run()


if __name__ == "__main__":
    main()