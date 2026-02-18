"""
Multi-cámara con mosaico (grid) + detección + Telegram
- Auto-detecta cámaras locales (probando índices 0..max-index)
- (Opcional) Auto-incluye URLs desde .env: MULTICAM_URLS="http://.../video,rtsp://..."
- (Opcional) Permite pasar fuentes manuales: --sources 0 --sources "http://.../video"
- Mosaico dinámico según número de cámaras
"""

import sys
import cv2
import time
import math
import argparse
import logging
import inspect
from pathlib import Path
from typing import List, Union, Optional

import numpy as np

# Asegura imports desde src/
sys.path.insert(0, str(Path(__file__).parent))

from camera.camera_manager import CameraManager
from detection.person_detector import PersonDetector
from alerts.telegram_alert import TelegramAlert
from utils.logger import setup_logger
from config import CAMERA_CONFIG, TELEGRAM_CONFIG, RECORDING_CONFIG


VideoSource = Union[int, str]


# -----------------------------
# Helpers mosaico
# -----------------------------
def compute_grid(n: int, cols: int) -> (int, int):
    cols = max(1, int(cols))
    rows = int(math.ceil(n / cols))
    return rows, cols


def make_tile(frame, tile_w: int, tile_h: int, label: Optional[str] = None):
    if frame is None:
        tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
        cv2.putText(tile, "SIN SEÑAL", (20, tile_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        return tile

    resized = cv2.resize(frame, (tile_w, tile_h), interpolation=cv2.INTER_AREA)

    if label:
        cv2.rectangle(resized, (0, 0), (tile_w, 28), (0, 0, 0), -1)
        cv2.putText(resized, label, (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return resized


def build_mosaic(frames: List, labels: List[str], tile_w: int, tile_h: int, cols: int):
    n = len(frames)
    rows, cols = compute_grid(n, cols)

    mosaic_rows = []
    idx = 0
    for _r in range(rows):
        row_tiles = []
        for _c in range(cols):
            if idx < n:
                row_tiles.append(make_tile(frames[idx], tile_w, tile_h, labels[idx]))
            else:
                row_tiles.append(make_tile(None, tile_w, tile_h, None))
            idx += 1
        mosaic_rows.append(np.hstack(row_tiles))

    return np.vstack(mosaic_rows)


def auto_cols(n: int) -> int:
    """Columnas automáticas razonables para mosaico."""
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 4:
        return 2
    if n <= 6:
        return 3
    return 4


# -----------------------------
# CLI
# -----------------------------
def parse_sources(values: List[str]) -> List[VideoSource]:
    """
    Permite:
      --sources 0 --sources http://...   (repetido)
      --sources "0,http://.../video"     (separado por comas)
    """
    out: List[VideoSource] = []
    for v in values:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        for p in parts:
            out.append(int(p) if p.isdigit() else p)
    return out


def build_args():
    p = argparse.ArgumentParser(description="Videovigilancia - MOSAICO multi-cámara")

    p.add_argument("--sources", action="append", default=[],
                   help='Fuentes manuales. Repite: --sources 0 --sources "http://.../video" (o separa por comas)')

    # Auto-detección de cámaras locales
    p.add_argument("--auto-local", action="store_true",
                   help="Auto-detectar cámaras locales (índices 0..max-index)")
    p.add_argument("--max-index", type=int, default=4,
                   help="Máximo índice a probar para cámaras locales (0..max-index)")

    # Auto-URLs desde .env
    p.add_argument("--auto-urls", action="store_true",
                   help='Auto-incluir URLs desde variable .env MULTICAM_URLS="http://.../video,rtsp://..."')

    # Mosaico
    p.add_argument("--cols", type=int, default=0,
                   help="Columnas del mosaico (0 = automático)")
    p.add_argument("--tile-w", type=int, default=640,
                   help="Ancho de cada tile")
    p.add_argument("--tile-h", type=int, default=360,
                   help="Alto de cada tile")

    # Baja latencia (útil con MJPEG/RTSP)
    p.add_argument("--drop-frames", type=int, default=0,
                   help="Saltar N frames antes de leer (reduce latencia en URLs). Ej: 5..15")

    # Ejecución
    p.add_argument("--no-gui", action="store_true", help="No mostrar ventana (modo headless)")
    p.add_argument("--duration", type=int, default=0, help="Segundos para auto-salida (0 = sin límite)")

    # Detección/alertas
    p.add_argument("--detect-every", type=int, default=1,
                   help="Detectar cada N frames por cámara (1 = cada frame, 2 = uno sí uno no...)")
    p.add_argument("--alert-cooldown", type=int, default=30,
                   help="Cooldown de alertas por cámara (segundos)")

    return p.parse_args()


# -----------------------------
# Auto-descubrimiento
# -----------------------------
def probe_local_cameras(max_index: int) -> List[int]:
    """
    OpenCV no lista cámaras; se hace por probe de índices.
    Nota: en macOS a veces sólo aparece la 0 (normal).
    """
    found = []
    for i in range(0, max_index + 1):
        cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else 0)
        ok = cap.isOpened()
        if ok:
            ret, _ = cap.read()
            if ret:
                found.append(i)
        cap.release()
    return found


def read_urls_from_env() -> List[str]:
    """
    Lee MULTICAM_URLS del entorno (cargado por dotenv en config.py).
    Ejemplo en .env:
      MULTICAM_URLS="http://192.168.1.108:8080/video,rtsp://192.168.1.50:8554/live.sdp"
    """
    import os
    raw = (os.getenv("MULTICAM_URLS") or "").strip()
    if not raw:
        return []
    # Permite comillas en .env
    raw = raw.strip('"').strip("'")
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return urls


# -----------------------------
# MultiCamApp
# -----------------------------
class MultiCamApp:
    def __init__(
        self,
        sources: List[VideoSource],
        cols: int,
        tile_w: int,
        tile_h: int,
        drop_frames: int,
        show_gui: bool,
        duration: int,
        detect_every: int,
        alert_cooldown: int,
    ):
        self.logger = setup_logger(__name__, logging.INFO)
        self.sources = sources
        self.cols = cols if cols > 0 else auto_cols(len(sources))
        self.tile_w = tile_w
        self.tile_h = tile_h
        self.drop_frames = max(0, int(drop_frames or 0))
        self.show_gui = show_gui
        self.duration = int(duration or 0)

        self.detect_every = max(1, int(detect_every or 1))
        self.alert_cooldown = max(0, int(alert_cooldown or 0))

        self.cams: List[CameraManager] = []
        self.labels: List[str] = []
        self.detectors: List[PersonDetector] = []
        self.last_alert_ts: List[float] = []

        self.telegram = None
        if TELEGRAM_CONFIG.get("enabled"):
            self.telegram = TelegramAlert(TELEGRAM_CONFIG["bot_token"], TELEGRAM_CONFIG["chat_id"])
            self.logger.info("Alertas por Telegram habilitadas")

        self._init_cameras()

    def _init_cameras(self):
        self.logger.info(f"Fuentes a iniciar: {self.sources}")

        for idx, src in enumerate(self.sources):
            cam_name = f"CAM{idx+1}"
            label = f"{cam_name} | {src}"
            self.labels.append(label)

            cfg = dict(CAMERA_CONFIG)

            # Pasamos source (URL) o camera_index (int)
            if isinstance(src, int):
                cfg["camera_index"] = src
                cfg.pop("source", None)
            else:
                cfg["source"] = src
                cfg.pop("camera_index", None)

            # Filtrar cfg según __init__ real del CameraManager
            cfg = self._filter_kwargs(CameraManager.__init__, cfg)

            cam = CameraManager(**cfg)
            ok = cam.init_camera()
            self.logger.info(f"[{cam_name}] init_camera={ok} source={src!r}")

            self.cams.append(cam)

            # Detector por cámara (independiente)
            self.detectors.append(PersonDetector(
                confidence_threshold=0.35,
                min_area=1500,
                min_persistence_frames=3,
                cooldown_seconds=30
            ))

            self.last_alert_ts.append(0.0)

    @staticmethod
    def _filter_kwargs(callable_obj, kwargs: dict) -> dict:
        try:
            sig = inspect.signature(callable_obj)
            allowed = set(sig.parameters.keys())
            return {k: v for k, v in kwargs.items() if k in allowed}
        except Exception:
            return kwargs

    def _read_cam(self, i: int):
        cam = self.cams[i]
        cap = getattr(cam, "cap", None)
        src = self.sources[i]

        # Baja latencia: saltar frames sólo en URLs
        if isinstance(src, str) and self.drop_frames > 0 and cap is not None:
            for _ in range(self.drop_frames):
                cap.grab()

        ok, frame = cam.get_frame()
        return ok, frame

    def _send_alert(self, cam_index: int, message: str, frame):
        if not self.telegram:
            return

        # Guardar imagen anotada para enviar
        Path("logs").mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        p = Path("logs") / f"alert_cam{cam_index+1}_{ts}.jpg"
        cv2.imwrite(str(p), frame)
        self.telegram.send_alert_async(message, str(p))

    def run(self):
        start = time.time()
        frame_counter = 0

        self.logger.info(f"Mostrando mosaico: cols={self.cols}, tile={self.tile_w}x{self.tile_h}, drop_frames={self.drop_frames}")
        self.logger.info("Pulsa 'q' para salir (si GUI).")

        try:
            while True:
                if self.duration > 0 and (time.time() - start) >= self.duration:
                    self.logger.info(f"Duración alcanzada ({self.duration}s). Saliendo...")
                    break

                frame_counter += 1

                annotated_frames = []

                for i in range(len(self.cams)):
                    ok, frame = self._read_cam(i)
                    if not ok or frame is None:
                        annotated_frames.append(None)
                        continue

                    # Detección cada N frames (para bajar CPU)
                    if frame_counter % self.detect_every == 0:
                        detected, annotated = self.detectors[i].detect(frame)
                    else:
                        detected = False
                        annotated = frame

                    annotated_frames.append(annotated)

                    # Alertas por cámara con cooldown
                    if detected and self.alert_cooldown > 0:
                        now = time.time()
                        if now - self.last_alert_ts[i] >= self.alert_cooldown:
                            self.last_alert_ts[i] = now
                            msg = f"🚨 PERSONA DETECTADA en CAM{i+1}\n{time.strftime('%Y-%m-%d %H:%M:%S')}"
                            self._send_alert(i, msg, annotated)

                # Construir mosaico
                mosaic = build_mosaic(annotated_frames, self.labels, self.tile_w, self.tile_h, self.cols)

                # Overlay de estado
                status = f"Cams: {len(self.cams)} | Frames: {frame_counter} | detect_every: {self.detect_every}"
                cv2.rectangle(mosaic, (0, 0), (mosaic.shape[1], 26), (0, 0, 0), -1)
                cv2.putText(mosaic, status, (10, 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

                if self.show_gui:
                    cv2.imshow("Videovigilancia - MOSAICO", mosaic)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self.logger.info("Salida solicitada por usuario")
                        break

        finally:
            for cam in self.cams:
                try:
                    cam.release()
                except Exception:
                    pass
            if self.show_gui:
                cv2.destroyAllWindows()


def main():
    args = build_args()

    sources: List[VideoSource] = []

    # 1) fuentes manuales
    if args.sources:
        sources.extend(parse_sources(args.sources))

    # 2) auto local
    if args.auto_local:
        local = probe_local_cameras(args.max_index)
        for idx in local:
            if idx not in sources:
                sources.append(idx)

    # 3) auto urls desde env
    if args.auto_urls:
        urls = read_urls_from_env()
        for u in urls:
            if u not in sources:
                sources.append(u)

    if not sources:
        print("No hay fuentes. Usa --sources o --auto-local o --auto-urls.")
        print('Ejemplo: python3 src/main_multicam.py --auto-local --max-index 3 --auto-urls')
        sys.exit(1)

    app = MultiCamApp(
        sources=sources,
        cols=args.cols,
        tile_w=args.tile_w,
        tile_h=args.tile_h,
        drop_frames=args.drop_frames,
        show_gui=(not args.no_gui),
        duration=args.duration,
        detect_every=args.detect_every,
        alert_cooldown=args.alert_cooldown,
    )
    app.run()


if __name__ == "__main__":
    main()