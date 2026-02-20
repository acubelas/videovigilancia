"""
Multi-cámara con mosaico (AUTO) + detección + Telegram

✅ NOMBRES desde .env:
- MULTICAM_CONFIG="Mac=0,Android=http://.../video,iPad=rtsp://.../stream"

✅ Por defecto: muestra TODAS las cámaras configuradas.
   Si una falla -> tile "SIN SEÑAL"

Opcional:
- --hide-offline  -> oculta cámaras offline (solo disponibles)
- --drop-frames N -> reduce latencia en URLs MJPEG/RTSP saltando frames antiguos
"""

import sys
import cv2
import time
import math
import argparse
import logging
import inspect
from pathlib import Path
from typing import List, Union, Optional, Tuple

import numpy as np

# Asegura imports desde src/
sys.path.insert(0, str(Path(__file__).parent))

from camera.camera_manager import CameraManager
from detection.person_detector import PersonDetector
from alerts.telegram_alert import TelegramAlert
from utils.logger import setup_logger
from config import CAMERA_CONFIG, TELEGRAM_CONFIG


VideoSource = Union[int, str]
NamedSource = Tuple[str, VideoSource]


# -----------------------------
# Helpers mosaico
# -----------------------------
def auto_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 4:
        return 2
    if n <= 6:
        return 3
    return 4


def compute_grid(n: int, cols: int) -> (int, int):
    cols = max(1, int(cols))
    rows = int(math.ceil(n / cols))
    return rows, cols


def make_tile(frame, tile_w: int, tile_h: int, label: Optional[str] = None):
    if frame is None:
        tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
        cv2.putText(tile, "SIN SEÑAL", (20, tile_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        if label:
            cv2.rectangle(tile, (0, 0), (tile_w, 28), (0, 0, 0), -1)
            cv2.putText(tile, label, (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
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


# -----------------------------
# Fuentes desde .env con NOMBRES
# -----------------------------
def read_named_sources_from_env() -> List[NamedSource]:
    """
    Lee MULTICAM_CONFIG del entorno (dotenv ya cargado por config.py):
      MULTICAM_CONFIG="Mac=0,Android=http://.../video,iPad=rtsp://.../stream"

    Devuelve lista [(name, source), ...]
    """
    import os
    raw = (os.getenv("MULTICAM_CONFIG") or "").strip()
    if not raw:
        return []
    raw = raw.strip('"').strip("'")

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: List[NamedSource] = []

    for p in parts:
        if "=" in p:
            name, src_txt = p.split("=", 1)
            name = name.strip()
            src_txt = src_txt.strip()
        else:
            # si no hay nombre, usamos CAMx
            name = ""
            src_txt = p.strip()

        source: VideoSource = int(src_txt) if src_txt.isdigit() else src_txt
        out.append((name, source))

    # Rellenar nombres vacíos
    final: List[NamedSource] = []
    for i, (name, src) in enumerate(out, start=1):
        final.append((name if name else f"CAM{i}", src))
    return final


def dedup_named_sources(items: List[NamedSource]) -> List[NamedSource]:
    """Elimina duplicados por source conservando el primer nombre."""
    seen = set()
    out = []
    for name, src in items:
        key = str(src)
        if key not in seen:
            seen.add(key)
            out.append((name, src))
    return out


# -----------------------------
# CLI
# -----------------------------
def build_args():
    p = argparse.ArgumentParser(description="Videovigilancia - MOSAICO multi-cámara (configuradas)")

    p.add_argument("--configured", action="store_true",
                   help='Usar fuentes de .env via MULTICAM_CONFIG="Nombre=Fuente,..."')

    p.add_argument("--hide-offline", action="store_true",
                   help="Ocultar cámaras que no estén disponibles (solo mostrar las que abran OK)")

    p.add_argument("--cols", type=int, default=0, help="Columnas (0=auto)")
    p.add_argument("--tile-w", type=int, default=640, help="Ancho tile")
    p.add_argument("--tile-h", type=int, default=360, help="Alto tile")

    p.add_argument("--drop-frames", type=int, default=0,
                   help="Saltar N frames antes de leer (URLs). Ej: 5..15")

    p.add_argument("--no-gui", action="store_true")
    p.add_argument("--duration", type=int, default=0, help="Segundos para auto-salida (0=sin límite)")

    p.add_argument("--detect-every", type=int, default=1,
                   help="Detectar cada N frames (1=cada frame, 2=uno sí uno no...)")
    p.add_argument("--alert-cooldown", type=int, default=30,
                   help="Cooldown alertas por cámara (0=desactivar alertas)")

    return p.parse_args()


# -----------------------------
# MultiCamApp
# -----------------------------
class MultiCamApp:
    def __init__(
        self,
        named_sources: List[NamedSource],
        cols: int,
        tile_w: int,
        tile_h: int,
        drop_frames: int,
        show_gui: bool,
        duration: int,
        detect_every: int,
        alert_cooldown: int,
        keep_offline: bool,  # True => mostrar SIN SEÑAL
    ):
        self.logger = setup_logger(__name__, logging.INFO)

        self.configured: List[NamedSource] = named_sources[:]
        self.keep_offline = keep_offline

        self.tile_w = tile_w
        self.tile_h = tile_h
        self.drop_frames = max(0, int(drop_frames or 0))
        self.show_gui = show_gui
        self.duration = int(duration or 0)

        self.detect_every = max(1, int(detect_every or 1))
        self.alert_cooldown = max(0, int(alert_cooldown or 0))

        # Listas alineadas
        self.names_active: List[str] = []
        self.sources_active: List[VideoSource] = []
        self.cams: List[Optional[CameraManager]] = []   # None => SIN SEÑAL
        self.labels: List[str] = []
        self.detectors: List[PersonDetector] = []
        self.last_alert_ts: List[float] = []

        self.telegram = None
        if TELEGRAM_CONFIG.get("enabled") and TELEGRAM_CONFIG.get("bot_token") and TELEGRAM_CONFIG.get("chat_id"):
            self.telegram = TelegramAlert(TELEGRAM_CONFIG["bot_token"], TELEGRAM_CONFIG["chat_id"])
            self.logger.info("Alertas por Telegram habilitadas")

        self._init_cameras()

        self.cols = cols if cols > 0 else auto_cols(len(self.sources_active))

        self.logger.info(
            f"Mosaico: tiles={len(self.sources_active)} cols={self.cols} tile={self.tile_w}x{self.tile_h} "
            f"drop_frames={self.drop_frames} detect_every={self.detect_every} keep_offline={self.keep_offline}"
        )

    @staticmethod
    def _filter_kwargs(callable_obj, kwargs: dict) -> dict:
        try:
            sig = inspect.signature(callable_obj)
            allowed = set(sig.parameters.keys())
            return {k: v for k, v in kwargs.items() if k in allowed}
        except Exception:
            return kwargs

    def _init_cameras(self):
        self.logger.info(f"Cámaras configuradas (con nombre): {self.configured}")

        for name, src in self.configured:
            cfg = dict(CAMERA_CONFIG)

            if isinstance(src, int):
                cfg["camera_index"] = src
                cfg.pop("source", None)
            else:
                cfg["source"] = src
                cfg.pop("camera_index", None)

            cfg = self._filter_kwargs(CameraManager.__init__, cfg)

            cam = CameraManager(**cfg)
            ok = cam.init_camera()
            self.logger.info(f"[{name}] init_camera={ok} source={src!r}")

            if not ok and not self.keep_offline:
                self.logger.warning(f"[{name}] NO disponible, se omite del mosaico: {src!r}")
                try:
                    cam.release()
                except Exception:
                    pass
                continue

            # Siempre añadimos (ok -> cam, fail -> None)
            self.names_active.append(name)
            self.sources_active.append(src)
            self.cams.append(cam if ok else None)

            # Etiqueta corta: CAMx | Nombre
            cam_idx = len(self.sources_active)
            self.labels.append(f"CAM{cam_idx} | {name}")

            self.detectors.append(PersonDetector(
                confidence_threshold=0.35,
                min_area=1500,
                min_persistence_frames=3,
                cooldown_seconds=30
            ))
            self.last_alert_ts.append(0.0)

        if not self.sources_active:
            raise RuntimeError("Ninguna cámara disponible para mostrar (revisa MULTICAM_CONFIG).")

    def _read_cam(self, i: int):
        cam = self.cams[i]
        src = self.sources_active[i]

        if cam is None:
            return False, None

        cap = getattr(cam, "cap", None)
        if isinstance(src, str) and self.drop_frames > 0 and cap is not None:
            for _ in range(self.drop_frames):
                cap.grab()

        return cam.get_frame()

    def _send_alert(self, cam_index: int, message: str, frame):
        if not self.telegram:
            return

        Path("logs").mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")

        # Nombre seguro para fichero (sin espacios raros)
        cam_name = self.names_active[cam_index]
        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in cam_name)

        photo_path = Path("logs") / f"alert_{cam_index+1:02d}_{safe_name}_{ts}.jpg"
        cv2.imwrite(str(photo_path), frame)

        self.telegram.send_alert_async(message, str(photo_path))

    def run(self):
        start = time.time()
        frame_counter = 0
        self.logger.info("Pulsa 'q' para salir (si GUI).")

        try:
            while True:
                if self.duration > 0 and (time.time() - start) >= self.duration:
                    self.logger.info(f"Duración alcanzada ({self.duration}s). Saliendo...")
                    break

                frame_counter += 1
                annotated_frames = []

                for i in range(len(self.sources_active)):
                    ok, frame = self._read_cam(i)
                    if not ok or frame is None:
                        annotated_frames.append(None)
                        continue

                    if frame_counter % self.detect_every == 0:
                        detected, annotated = self.detectors[i].detect(frame)
                    else:
                        detected = False
                        annotated = frame

                    annotated_frames.append(annotated)

                    if detected and self.alert_cooldown > 0:
                        now = time.time()
                        if now - self.last_alert_ts[i] >= self.alert_cooldown:
                            self.last_alert_ts[i] = now

                            cam_name = self.names_active[i]
                            cam_tag = f"CAM{i+1}"

                            msg = (
                                f"🚨 PERSONA DETECTADA en {cam_name} ({cam_tag})\n"
                                f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )

                            self._send_alert(i, msg, annotated)

                mosaic = build_mosaic(annotated_frames, self.labels, self.tile_w, self.tile_h, self.cols)

                status = f"Cams:{len(self.sources_active)} | Frame:{frame_counter} | detect_every:{self.detect_every}"
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
                    if cam is not None:
                        cam.release()
                except Exception:
                    pass
            if self.show_gui:
                cv2.destroyAllWindows()


def main():
    args = build_args()

    if not args.configured:
        print("Usa --configured y define MULTICAM_CONFIG en tu .env.")
        sys.exit(1)

    named = read_named_sources_from_env()
    named = dedup_named_sources(named)

    if not named:
        print("No hay cámaras configuradas.")
        print('Añade en .env: MULTICAM_CONFIG="Mac=0,Android=http://192.168.1.108:8080/video,iPad=rtsp://192.168.1.141:8554/stream"')
        sys.exit(1)

    # ✅ DEFAULT: mostrar offline como SIN SEÑAL
    keep_offline = not args.hide_offline

    app = MultiCamApp(
        named_sources=named,
        cols=args.cols,              # 0 => auto
        tile_w=args.tile_w,
        tile_h=args.tile_h,
        drop_frames=args.drop_frames,
        show_gui=(not args.no_gui),
        duration=args.duration,
        detect_every=args.detect_every,
        alert_cooldown=args.alert_cooldown,
        keep_offline=keep_offline,
    )
    app.run()


if __name__ == "__main__":
    main()