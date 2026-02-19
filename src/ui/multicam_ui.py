# -*- coding: utf-8 -*-
"""Videovigilancia - UI Multicámara (DEFINITIVO + Wi‑Fi + Telegram destinos)

✅ Mantiene lo anterior:
- Wi‑Fi: primera vez seleccionar y guardar; si coincide no muestra ventana; si no coincide avisa.
- Listado de Wi‑Fis por networksetup -listpreferredwirelessnetworks (fiable en macOS moderno).
- Toolbar con scroll horizontal inferior (para ver todos los botones).
- Previsualización con scroll vertical.
- Tabla estable (no pierde selección), doble click para activar/desactivar.
- CRUD cámaras + autosave en .env (MULTICAM_CONFIG / MULTICAM_DISABLED).
- Escaneo webcams locales + escaneo red (Android IP Webcam / RTSP 8554/554).
- Detección de personas + alertas (incluye fecha/hora en el mensaje Telegram).

✅ Añade Telegram multi-destinatario configurable desde la UI:
- Dos listas: Usuarios (privado) y Grupos/Canales
- Si ambas listas tienen IDs => envía a TODOS
- Botón “Añadir…” con selector Usuario vs Grupo/Canal
- Importar desde getUpdates

Requisitos .env:
- TELEGRAM_BOT_TOKEN=...
- (opcional) TELEGRAM_USER_CHAT_IDS=... / TELEGRAM_GROUP_CHAT_IDS=...
- (opcional) CAMERA_WIFI_SSID=... (se gestiona desde la UI)
"""

import os
import cv2
import time
import threading
import subprocess
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import numpy as np

from dotenv import load_dotenv
load_dotenv()

from src.detection.person_detector import PersonDetector
from src.alerts.telegram_alert import TelegramAlert
from src.camera.discovery import discover_local_cameras


# ------------------------------
# CONFIG ENV
# ------------------------------
MULTICAM_RAW = os.getenv("MULTICAM_CONFIG", "")
DISABLED_RAW = os.getenv("MULTICAM_DISABLED", "")
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "models/yolov8n.pt")

CAMERA_WIFI_SSID = os.getenv("CAMERA_WIFI_SSID", "").strip()
AUTO_SAVE_ENV = True

# Telegram global (se recarga cuando guardas en UI)
TELEGRAM = TelegramAlert.from_env()


# ------------------------------
# WIFI util (macOS)
# ------------------------------
def get_current_ssid_macos():
    """Obtiene el SSID actual (si está conectado) usando networksetup."""
    for iface in ("en0", "en1"):
        try:
            r = subprocess.run(
                ["/usr/sbin/networksetup", "-getairportnetwork", iface],
                capture_output=True, text=True, timeout=2
            )
            out = (r.stdout or "").strip()
            if "Current Wi-Fi Network:" in out:
                ssid = out.split("Current Wi-Fi Network:", 1)[1].strip()
                if ssid and "not associated" not in ssid.lower():
                    return ssid
        except Exception:
            pass
    return ""


def list_preferred_ssids_macos():
    """Lista redes guardadas/preferidas en macOS (no depende de escaneo)."""
    ssids = []
    for iface in ("en0", "en1"):
        try:
            r = subprocess.run(
                ["/usr/sbin/networksetup", "-listpreferredwirelessnetworks", iface],
                capture_output=True, text=True, timeout=3
            )
            lines = (r.stdout or "").splitlines()
            for line in lines[1:]:
                s = line.strip()
                if s and s not in ssids:
                    ssids.append(s)
        except Exception:
            pass
    return ssids


def prioritize_current_ssid(ssids, current_ssid):
    """Pone la Wi‑Fi actual la primera en el desplegable."""
    if not ssids:
        return ssids
    if current_ssid and current_ssid in ssids:
        ssids = [s for s in ssids if s != current_ssid]
        ssids.insert(0, current_ssid)
    return ssids


def open_wifi_settings_macos():
    """Abre Ajustes del Sistema en la sección Wi‑Fi."""
    try:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.Wi-Fi-Settings.extension"])
        return
    except Exception:
        pass
    try:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.network"])
    except Exception:
        pass


# ------------------------------
# ENV helpers
# ------------------------------
def update_env_key(key: str, value: str, env_path=".env"):
    """Actualiza/crea KEY=VALUE en .env preservando el resto."""
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_disabled_names(raw: str) -> set:
    raw = (raw or "").strip()
    if not raw:
        return set()
    return {x.strip() for x in raw.split(",") if x.strip()}


def parse_multicam_env(raw: str):
    out = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            if v.isdigit():
                out[k] = int(v)
            else:
                out[k] = v
    return out


def format_multicam_env(d: dict):
    return ",".join([f"{k}={v}" for k, v in d.items()])


def save_env_state(cameras: dict):
    cfg = {name: info["src"] for name, info in cameras.items()}
    disabled = [name for name, info in cameras.items() if not info.get("enabled", True)]
    update_env_key("MULTICAM_CONFIG", format_multicam_env(cfg))
    update_env_key("MULTICAM_DISABLED", ",".join(disabled))


# ------------------------------
# Telegram env helpers
# ------------------------------
def load_telegram_ids_from_env():
    user_ids = TelegramAlert.parse_ids(os.getenv("TELEGRAM_USER_CHAT_IDS", "").strip())
    group_ids = TelegramAlert.parse_ids(os.getenv("TELEGRAM_GROUP_CHAT_IDS", "").strip())

    # Compat legacy
    legacy_single = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    legacy_multi = os.getenv("TELEGRAM_CHAT_IDS", "").strip()

    if legacy_single and legacy_single not in user_ids and legacy_single not in group_ids:
        user_ids.append(legacy_single)
    for x in TelegramAlert.parse_ids(legacy_multi):
        if x not in user_ids and x not in group_ids:
            user_ids.append(x)

    return user_ids, group_ids


def save_telegram_ids_to_env(user_ids, group_ids):
    update_env_key("TELEGRAM_USER_CHAT_IDS", ",".join(user_ids))
    update_env_key("TELEGRAM_GROUP_CHAT_IDS", ",".join(group_ids))


# ------------------------------
# Alerts Telegram
# ------------------------------
def send_telegram_alert(camera_name: str, frame):
    global TELEGRAM
    if TELEGRAM is None:
        return

    ahora = datetime.now()
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    stamp = f"{dias[ahora.weekday()]} {ahora.strftime('%d/%m/%Y %H:%M:%S')}"

    os.makedirs("logs", exist_ok=True)
    ts_file = ahora.strftime("%Y%m%d_%H%M%S")
    tmp_path = f"logs/alert_tmp_{camera_name}_{ts_file}.jpg"

    ok, jpg = cv2.imencode(".jpg", frame)
    if ok:
        with open(tmp_path, "wb") as f:
            f.write(jpg.tobytes())

    msg = f"🚨 Persona detectada\n📷 Cámara: {camera_name}\n🕒 {stamp}"
    TELEGRAM.send_alert_async(msg, photo_path=tmp_path if ok else None)

    def cleanup(p=tmp_path):
        time.sleep(5)
        try:
            os.remove(p)
        except Exception:
            pass

    threading.Thread(target=cleanup, daemon=True).start()


# ------------------------------
# Worker cámara
# ------------------------------
DETECT_LOCK = threading.Lock()


class CamWorker(threading.Thread):
    def __init__(self, name, src, enabled=True, android_drop=12):
        super().__init__(daemon=True)
        self.name = name
        self.src = src
        self.enabled = enabled
        self.android_drop = android_drop if (isinstance(src, str) and ":8080/video" in src) else 0
        self.stop_evt = threading.Event()
        self.frame = None
        self.status = "Parada"
        self.cap = None

        self.detector = PersonDetector(
            model_path=YOLO_MODEL_PATH,
            confidence_threshold=0.35,
            min_persistence_frames=3,
            cooldown_seconds=30
        )

    def stop(self):
        self.stop_evt.set()

    def stop_and_join(self, timeout=1.5):
        self.stop()
        try:
            self.join(timeout=timeout)
        except Exception:
            pass

    def _open(self):
        src = self.src
        if isinstance(src, str) and src.strip().isdigit():
            src = int(src.strip())
        self.cap = cv2.VideoCapture(src)
        if self.android_drop > 0:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _offline(self):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(blank, "SIN SEÑAL", (150, 250),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (200, 200, 200), 3)
        return blank

    def run(self):
        if not self.enabled:
            self.status = "Desactivada"
            return

        self.status = "Abriendo..."
        self._open()

        if not (self.cap and self.cap.isOpened()):
            self.status = "Sin señal"
        else:
            self.status = "Activa"

        while not self.stop_evt.is_set():
            if not (self.cap and self.cap.isOpened()):
                self.status = "Reconectando..."
                time.sleep(0.5)
                self._open()
                if not (self.cap and self.cap.isOpened()):
                    self.frame = self._offline()
                    continue

            if self.android_drop > 0:
                for _ in range(self.android_drop):
                    self.cap.read()

            ok, frame = self.cap.read()
            if not ok:
                self.status = "Sin señal"
                self.frame = self._offline()
                time.sleep(0.15)
                continue

            self.status = "Activa"

            with DETECT_LOCK:
                confirmed, annotated = self.detector.detect(frame)

            self.frame = annotated

            if confirmed:
                send_telegram_alert(self.name, annotated)

        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass

        self.status = "Parada"


# ------------------------------
# Mosaic (letterbox)
# ------------------------------
def _letterbox(img, tile_w=480, tile_h=270, color=(0, 0, 0)):
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

    scale = min(tile_w / w, tile_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = cv2.resize(img, (new_w, new_h))
    canvas = np.full((tile_h, tile_w, 3), color, dtype=np.uint8)

    y = (tile_h - new_h) // 2
    x = (tile_w - new_w) // 2
    canvas[y:y + new_h, x:x + new_w] = resized
    return canvas


def draw_plate(img, name, status):
    color = (0, 255, 255) if status == "Activa" else (180, 180, 180)
    cv2.putText(img, name, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
    cv2.putText(img, f"[{status}]", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return img


def build_mosaic(named_frames, tile_w=480, tile_h=270, cols=2, bg_color=(0, 0, 0)):
    if not named_frames:
        return np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

    tiles = []
    for name, status, img in named_frames:
        if img is None:
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(img, "SIN SEÑAL", (150, 250),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (200, 200, 200), 3)

        tile = _letterbox(img, tile_w=tile_w, tile_h=tile_h, color=bg_color)
        tile = draw_plate(tile, name, status)
        tiles.append(tile)

    rows = []
    for i in range(0, len(tiles), cols):
        row = tiles[i:i + cols]
        if len(row) < cols:
            for _ in range(cols - len(row)):
                row.append(np.zeros((tile_h, tile_w, 3), dtype=np.uint8))
        rows.append(np.hstack(row))

    return np.vstack(rows)


# ------------------------------
# Descubrimiento red (Android IP Webcam / RTSP)
# ------------------------------
def get_local_ipv4():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def tcp_port_open(host, port, timeout=0.25):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def http_ipwebcam_ok(host, timeout=0.35):
    try:
        import requests
        r = requests.head(f"http://{host}:8080/video", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def scan_subnet_for_cameras(cidr=24, max_workers=64, stop_flag=None, progress_cb=None):
    ip = get_local_ipv4()
    if ip.startswith("127."):
        return []

    net = ipaddress.ip_network(f"{ip}/{cidr}", strict=False)
    hosts = [str(h) for h in net.hosts()]

    results = []
    total = len(hosts)
    done = 0

    def check_host(h):
        if stop_flag and stop_flag.is_set():
            return None

        if tcp_port_open(h, 8080, timeout=0.2) and http_ipwebcam_ok(h, timeout=0.3):
            return {"name": f"Android-{h}", "src": f"http://{h}:8080/video"}

        if tcp_port_open(h, 8554, timeout=0.2):
            return {"name": f"RTSP-{h}", "src": f"rtsp://{h}:8554/stream"}

        if tcp_port_open(h, 554, timeout=0.2):
            return {"name": f"RTSP-{h}", "src": f"rtsp://{h}:554/stream"}

        return None

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(check_host, h): h for h in hosts}
        for fut in as_completed(futs):
            if stop_flag and stop_flag.is_set():
                break
            item = fut.result()
            if item:
                results.append(item)

            done += 1
            if progress_cb and done % 10 == 0:
                progress_cb(done, total, len(results))

    return results


# ------------------------------
# UI
# ------------------------------
class MultiCamUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Videovigilancia - UI Multicámara")
        self.geometry("1120x720")

        self.cameras = {}
        self.workers = {}

        self._net_scan_stop = threading.Event()
        self._net_scan_thread = None

        self.camera_wifi_ssid = CAMERA_WIFI_SSID

        disabled = parse_disabled_names(DISABLED_RAW)
        initial = parse_multicam_env(MULTICAM_RAW)
        for name, src in initial.items():
            self.cameras[name] = {"src": src, "enabled": (name not in disabled), "status": "Parada"}

        self._build_ui()
        self._refresh_table()

        self.protocol("WM_DELETE_WINDOW", self.on_exit)

        if AUTO_SAVE_ENV:
            save_env_state(self.cameras)

        # Flujo Wi‑Fi al inicio
        self.after(400, self.first_run_wifi_flow)

        self._loop_preview()

    # Toolbar scroll horizontal + UI
    def _build_ui(self):
        toolbar_wrap = ttk.Frame(self)
        toolbar_wrap.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))

        self.toolbar_canvas = tk.Canvas(toolbar_wrap, height=48, highlightthickness=0)
        self.toolbar_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.toolbar_scroll_x = ttk.Scrollbar(toolbar_wrap, orient="horizontal", command=self.toolbar_canvas.xview)
        self.toolbar_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.toolbar_canvas.configure(xscrollcommand=self.toolbar_scroll_x.set)

        self.toolbar_frame = ttk.Frame(self.toolbar_canvas)
        self.toolbar_window = self.toolbar_canvas.create_window((0, 0), window=self.toolbar_frame, anchor="nw")

        def _on_toolbar_configure(event=None):
            self.toolbar_canvas.configure(scrollregion=self.toolbar_canvas.bbox("all"))

        def _on_canvas_resize(event=None):
            self.toolbar_canvas.itemconfig(self.toolbar_window, height=48)

        self.toolbar_frame.bind("<Configure>", _on_toolbar_configure)
        self.toolbar_canvas.bind("<Configure>", _on_canvas_resize)

        ttk.Button(self.toolbar_frame, text="Escanear webcams", command=self.scan_webcams_async).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Escanear red (IP/RTSP)", command=self.scan_network_async).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Telegram (destinos)", command=self.open_telegram_config).pack(side=tk.LEFT, padx=10)
        ttk.Button(self.toolbar_frame, text="Wi‑Fi (cambiar)", command=self.open_wifi_selector_anytime).pack(side=tk.LEFT, padx=10)

        ttk.Button(self.toolbar_frame, text="Añadir", command=self.add_cam).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Editar", command=self.edit_cam).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Eliminar (forzado)", command=self.delete_selected_forced).pack(side=tk.LEFT, padx=4)

        ttk.Button(self.toolbar_frame, text="Guardar ahora", command=self.save_env_now).pack(side=tk.LEFT, padx=10)
        ttk.Button(self.toolbar_frame, text="Iniciar", command=self.start_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Parar", command=self.stop_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(self.toolbar_frame, text="Salir", command=self.on_exit).pack(side=tk.LEFT, padx=6)

        # Tabla
        mid = ttk.Frame(self)
        mid.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        columns = ("enabled", "name", "src", "status")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", height=9, selectmode="browse")

        self.tree.heading("enabled", text="Activa")
        self.tree.heading("name", text="Nombre")
        self.tree.heading("src", text="Fuente/URL")
        self.tree.heading("status", text="Estado")

        self.tree.column("enabled", width=60, anchor="center")
        self.tree.column("name", width=160)
        self.tree.column("src", width=660)
        self.tree.column("status", width=120, anchor="center")

        self.tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        scroll_table = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_table.set)
        scroll_table.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self.toggle_enable_persistent)

        # Preview con scroll vertical
        preview = ttk.LabelFrame(self, text="Previsualización")
        preview.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=6)

        self.preview_canvas = tk.Canvas(preview, highlightthickness=0)
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview_scroll_y = ttk.Scrollbar(preview, orient="vertical", command=self.preview_canvas.yview)
        self.preview_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_canvas.configure(yscrollcommand=self.preview_scroll_y.set)

        self._preview_imgtk = None
        self._preview_img_id = None

        self.preview_canvas.bind("<Enter>", lambda e: self.preview_canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.preview_canvas.bind("<Leave>", lambda e: self.preview_canvas.unbind_all("<MouseWheel>"))

        self.status_var = tk.StringVar(value="Listo")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(side=tk.BOTTOM, fill=tk.X)

    def _on_mousewheel(self, event):
        delta = event.delta
        if delta == 0:
            return
        step = int(-1 * (delta / 120)) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.preview_canvas.yview_scroll(step, "units")

    # Tabla estable
    def _refresh_table(self):
        existing = set(self.tree.get_children())
        current = set(self.cameras.keys())

        for iid in existing - current:
            try:
                self.tree.delete(iid)
            except Exception:
                pass

        for name, info in self.cameras.items():
            values = (
                "Sí" if info.get("enabled", True) else "No",
                name,
                str(info.get("src")),
                info.get("status", "")
            )
            if name in existing:
                self.tree.item(name, values=values)
            else:
                self.tree.insert("", tk.END, iid=name, values=values)

    def _get_selected_name(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return sel[0]

    def _autosave(self):
        if AUTO_SAVE_ENV:
            save_env_state(self.cameras)

    # Cierre
    def on_exit(self):
        try:
            self._net_scan_stop.set()
        except Exception:
            pass

        try:
            self.stop_all()
        except Exception:
            pass

        try:
            self._autosave()
        except Exception:
            pass

        self.destroy()

    # ---------------------- Wi‑Fi flow ----------------------
    def first_run_wifi_flow(self):
        if not self.camera_wifi_ssid:
            self._wifi_select_dialog(first_time=True)
            return

        current = get_current_ssid_macos()
        if current and current == self.camera_wifi_ssid:
            # Conectado: no molestar
            self.scan_network_async()
            return

        self._wifi_mismatch_dialog(current_ssid=current)

    def open_wifi_selector_anytime(self):
        self._wifi_select_dialog(first_time=False)

    def _wifi_select_dialog(self, first_time=False):
        current = get_current_ssid_macos()
        ssids = list_preferred_ssids_macos()
        ssids = prioritize_current_ssid(ssids, current)

        win = tk.Toplevel(self)
        win.title("Selecciona Wi‑Fi de cámaras")
        win.geometry("620x300")
        win.transient(self)
        win.grab_set()

        txt = "Selecciona la Wi‑Fi donde están conectadas las cámaras.\nSe guardará y no molestará si ya estás conectado."
        if current:
            txt += f"\n\nWi‑Fi actual: {current}"
        ttk.Label(win, text=txt, justify="left", wraplength=580).pack(padx=12, pady=12, anchor="w")

        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, fill="x")

        ttk.Label(frm, text="Wi‑Fi:").pack(side=tk.LEFT, padx=6)
        wifi_var = tk.StringVar(value=current if current else (ssids[0] if ssids else ""))
        combo = ttk.Combobox(frm, textvariable=wifi_var, values=ssids, width=44, state="readonly" if ssids else "normal")
        combo.pack(side=tk.LEFT, padx=6)

        def refresh_list():
            cur = get_current_ssid_macos()
            new_list = list_preferred_ssids_macos()
            new_list = prioritize_current_ssid(new_list, cur)
            combo["values"] = new_list
            if new_list and not wifi_var.get().strip():
                wifi_var.set(new_list[0])

        ttk.Button(frm, text="Refrescar", command=refresh_list).pack(side=tk.LEFT, padx=6)

        btns = ttk.Frame(win)
        btns.pack(padx=12, pady=12, fill="x")

        def do_save():
            ssid = wifi_var.get().strip()
            if not ssid:
                messagebox.showwarning("Aviso", "Selecciona una Wi‑Fi.")
                return
            self.camera_wifi_ssid = ssid
            update_env_key("CAMERA_WIFI_SSID", ssid)
            win.destroy()
            self.status_var.set(f"Wi‑Fi guardada: {ssid}")
            self.scan_network_async()

        ttk.Button(btns, text="Abrir Ajustes Wi‑Fi", command=open_wifi_settings_macos).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Guardar", command=do_save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    def _wifi_mismatch_dialog(self, current_ssid=""):
        ssids = list_preferred_ssids_macos()
        ssids = prioritize_current_ssid(ssids, current_ssid)

        win = tk.Toplevel(self)
        win.title("Wi‑Fi de cámaras no detectada")
        win.geometry("680x340")
        win.transient(self)
        win.grab_set()

        msg = "No estás conectado a la Wi‑Fi guardada para las cámaras.\n\n"
        if current_ssid:
            msg += f"Wi‑Fi actual: {current_ssid}\n"
        msg += f"Wi‑Fi guardada: {self.camera_wifi_ssid}\n\n"
        msg += "Puedes abrir Ajustes Wi‑Fi, guardar otra Wi‑Fi de la lista o escanear la red actual."
        ttk.Label(win, text=msg, justify="left", wraplength=640).pack(padx=12, pady=12, anchor="w")

        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=6, fill="x")

        ttk.Label(frm, text="Guardar como Wi‑Fi de cámaras:").pack(side=tk.LEFT, padx=6)
        wifi_var = tk.StringVar(value=current_ssid if current_ssid else (ssids[0] if ssids else ""))
        combo = ttk.Combobox(frm, textvariable=wifi_var, values=ssids, width=44, state="readonly" if ssids else "normal")
        combo.pack(side=tk.LEFT, padx=6)

        def refresh_list():
            cur = get_current_ssid_macos()
            new_list = list_preferred_ssids_macos()
            new_list = prioritize_current_ssid(new_list, cur)
            combo["values"] = new_list
            if new_list and not wifi_var.get().strip():
                wifi_var.set(new_list[0])

        ttk.Button(frm, text="Refrescar", command=refresh_list).pack(side=tk.LEFT, padx=6)

        btns = ttk.Frame(win)
        btns.pack(padx=12, pady=12, fill="x")

        def do_save():
            ssid = wifi_var.get().strip()
            if not ssid:
                messagebox.showwarning("Aviso", "Selecciona una Wi‑Fi.")
                return
            self.camera_wifi_ssid = ssid
            update_env_key("CAMERA_WIFI_SSID", ssid)
            self.status_var.set(f"Wi‑Fi guardada: {ssid}")
            win.destroy()
            self.scan_network_async()

        ttk.Button(btns, text="Abrir Ajustes Wi‑Fi", command=open_wifi_settings_macos).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Guardar Wi‑Fi seleccionada", command=do_save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Escanear red ahora", command=lambda: (win.destroy(), self.scan_network_async())).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    # ---------------------- Telegram config ----------------------
    def open_telegram_config(self):
        global TELEGRAM

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            messagebox.showwarning("Telegram", "Falta TELEGRAM_BOT_TOKEN en .env")
            return

        user_ids, group_ids = load_telegram_ids_from_env()

        win = tk.Toplevel(self)
        win.title("Configuración Telegram - Destinatarios")
        win.geometry("760x460")
        win.transient(self)
        win.grab_set()

        info = (
            "Se enviará a TODOS los IDs listados (Usuarios + Grupos/Canales).\n\n"
            "- Usuarios: deben hacer /start al bot.\n"
            "- Grupos/Canales: añade el bot y escribe algo.\n\n"
            "Puedes importar chat_ids desde getUpdates (chats que ya han hablado con el bot)."
        )
        ttk.Label(win, text=info, justify="left", wraplength=720).pack(padx=12, pady=10, anchor="w")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        left = ttk.LabelFrame(container, text="Chats privados (usuarios)")
        left.pack(side=tk.LEFT, fill="both", expand=True, padx=(0, 6))

        lb_users = tk.Listbox(left, height=12)
        lb_users.pack(side=tk.LEFT, fill="both", expand=True, padx=6, pady=6)
        sb_u = ttk.Scrollbar(left, orient="vertical", command=lb_users.yview)
        sb_u.pack(side=tk.RIGHT, fill=tk.Y)
        lb_users.configure(yscrollcommand=sb_u.set)
        for x in user_ids:
            lb_users.insert(tk.END, x)

        right = ttk.LabelFrame(container, text="Grupos / canales")
        right.pack(side=tk.LEFT, fill="both", expand=True, padx=(6, 0))

        lb_groups = tk.Listbox(right, height=12)
        lb_groups.pack(side=tk.LEFT, fill="both", expand=True, padx=6, pady=6)
        sb_g = ttk.Scrollbar(right, orient="vertical", command=lb_groups.yview)
        sb_g.pack(side=tk.RIGHT, fill=tk.Y)
        lb_groups.configure(yscrollcommand=sb_g.set)
        for x in group_ids:
            lb_groups.insert(tk.END, x)

        actions = ttk.Frame(win)
        actions.pack(fill="x", padx=12, pady=10)

        def remove_selected(listbox):
            sel = listbox.curselection()
            for i in reversed(sel):
                listbox.delete(i)

        def add_destination():
            """Añadir… con selector Usuario / Grupo."""
            dlg = tk.Toplevel(win)
            dlg.title("Añadir destinatario")
            dlg.geometry("460x220")
            dlg.transient(win)
            dlg.grab_set()

            ttk.Label(dlg, text="Elige el tipo y pega el chat_id.", wraplength=420, justify="left")\
                .pack(padx=12, pady=10, anchor="w")

            kind = tk.StringVar(value="user")
            kinds = ttk.Frame(dlg)
            kinds.pack(padx=12, pady=6, fill="x")
            ttk.Radiobutton(kinds, text="Usuario (privado)", variable=kind, value="user").pack(side=tk.LEFT, padx=6)
            ttk.Radiobutton(kinds, text="Grupo/Canal", variable=kind, value="group").pack(side=tk.LEFT, padx=6)

            frm = ttk.Frame(dlg)
            frm.pack(padx=12, pady=8, fill="x")
            ttk.Label(frm, text="Chat ID:").pack(side=tk.LEFT, padx=6)
            chat_var = tk.StringVar(value="")
            ent = ttk.Entry(frm, textvariable=chat_var, width=28)
            ent.pack(side=tk.LEFT, padx=6)
            ent.focus_set()

            def do_add():
                val = chat_var.get().strip()
                if not val:
                    messagebox.showwarning("Aviso", "Introduce un chat_id.", parent=dlg)
                    return

                if kind.get() == "user":
                    existing = set(lb_users.get(0, tk.END))
                    if val not in existing:
                        lb_users.insert(tk.END, val)
                else:
                    existing = set(lb_groups.get(0, tk.END))
                    if val not in existing:
                        lb_groups.insert(tk.END, val)
                dlg.destroy()

            btns = ttk.Frame(dlg)
            btns.pack(padx=12, pady=10, fill="x")
            ttk.Button(btns, text="Añadir", command=do_add).pack(side=tk.LEFT, padx=4)
            ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

        def import_updates():
            """Importa chat_ids desde getUpdates y los clasifica automáticamente."""
            try:
                tg = TelegramAlert.from_env()
                if tg is None:
                    messagebox.showwarning("Telegram", "Config incompleta: TELEGRAM_BOT_TOKEN")
                    return
                data = tg.get_updates(limit=100)
                if not data.get("ok"):
                    messagebox.showwarning("Telegram", f"getUpdates error: {data}")
                    return

                discovered_users = set()
                discovered_groups = set()

                for upd in data.get("result", []):
                    msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post")
                    if not msg:
                        continue
                    chat = msg.get("chat", {})
                    cid = chat.get("id")
                    ctype = chat.get("type")
                    if cid is None:
                        continue
                    cid_str = str(cid)

                    if ctype in ("group", "supergroup", "channel") or cid_str.startswith("-100") or cid_str.startswith("-"):
                        discovered_groups.add(cid_str)
                    else:
                        discovered_users.add(cid_str)

                if not (discovered_users or discovered_groups):
                    messagebox.showinfo("Telegram", "No se han encontrado chats en getUpdates. Pide /start o escribe en el grupo.")
                    return

                existing_u = set(lb_users.get(0, tk.END))
                existing_g = set(lb_groups.get(0, tk.END))

                for cid in sorted(discovered_users):
                    if cid not in existing_u:
                        lb_users.insert(tk.END, cid)

                for cid in sorted(discovered_groups):
                    if cid not in existing_g:
                        lb_groups.insert(tk.END, cid)

                messagebox.showinfo("Telegram", "Importación completada desde getUpdates")

            except Exception as e:
                messagebox.showerror("Telegram", f"Error importando getUpdates: {e}")

        def save_and_close():
            """Guarda en .env y recarga instancia global TELEGRAM."""
            global TELEGRAM
            u = [x.strip() for x in lb_users.get(0, tk.END) if str(x).strip()]
            g = [x.strip() for x in lb_groups.get(0, tk.END) if str(x).strip()]

            save_telegram_ids_to_env(u, g)
            TELEGRAM = TelegramAlert.from_env()

            messagebox.showinfo("Telegram", "Destinatarios guardados en .env")
            win.destroy()

        ttk.Button(actions, text="Añadir…", command=add_destination).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Quitar usuario", command=lambda: remove_selected(lb_users)).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Quitar grupo", command=lambda: remove_selected(lb_groups)).pack(side=tk.LEFT, padx=4)

        ttk.Button(actions, text="Importar desde getUpdates", command=import_updates).pack(side=tk.LEFT, padx=12)

        ttk.Button(actions, text="Guardar", command=save_and_close).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    # ---------------------- CRUD + scans + start/stop ----------------------
    def _unique_name(self, desired: str) -> str:
        if desired not in self.cameras:
            return desired
        base = desired
        n = 2
        while f"{base}-{n}" in self.cameras:
            n += 1
        return f"{base}-{n}"

    def add_cam(self):
        name = simpledialog.askstring("Nueva cámara", "Nombre:")
        if not name:
            return
        name = self._unique_name(name.strip())

        src = simpledialog.askstring("Nueva cámara", "Fuente (índice/URL):")
        if not src:
            return
        src = src.strip()
        if src.isdigit():
            src = int(src)

        self.cameras[name] = {"src": src, "enabled": True, "status": "Parada"}
        self._autosave()
        self._refresh_table()

    def edit_cam(self):
        name = self._get_selected_name()
        if not name:
            messagebox.showinfo("Info", "Selecciona una cámara para editar")
            return

        info = self.cameras.get(name)
        if not info:
            return

        new_name = simpledialog.askstring("Editar", "Nombre:", initialvalue=name)
        if not new_name:
            return
        new_name = new_name.strip()

        new_src = simpledialog.askstring("Editar", "Fuente:", initialvalue=str(info.get("src")))
        if not new_src:
            return
        new_src = new_src.strip()
        if new_src.isdigit():
            new_src = int(new_src)

        was_running = name in self.workers
        if was_running:
            self.workers[name].stop_and_join(timeout=1.5)
            del self.workers[name]

        enabled = info.get("enabled", True)

        if new_name != name:
            new_name = self._unique_name(new_name)
            del self.cameras[name]
            self.cameras[new_name] = {"src": new_src, "enabled": enabled, "status": "Parada"}
            name = new_name
        else:
            info["src"] = new_src
            info["status"] = "Parada"

        if was_running and self.cameras[name].get("enabled", True):
            w = CamWorker(name, self.cameras[name]["src"], enabled=True, android_drop=12)
            self.workers[name] = w
            w.start()

        self._autosave()
        self._refresh_table()

    def delete_selected_forced(self):
        name = self._get_selected_name()
        if not name:
            messagebox.showinfo("Info", "Selecciona una cámara")
            return
        if not messagebox.askyesno("Confirmar", f"¿Eliminar cámara '{name}' definitivamente?"):
            return

        if name in self.workers:
            self.workers[name].stop_and_join(timeout=1.5)
            del self.workers[name]

        if name in self.cameras:
            del self.cameras[name]

        self._autosave()
        self._refresh_table()

    def toggle_enable_persistent(self, event=None):
        name = self._get_selected_name()
        if not name:
            return
        info = self.cameras.get(name)
        if not info:
            return

        info["enabled"] = not info.get("enabled", True)

        if name in self.workers and not info["enabled"]:
            self.workers[name].stop_and_join(timeout=1.5)
            del self.workers[name]
            info["status"] = "Parada"
        elif name not in self.workers and info["enabled"] and self.workers:
            w = CamWorker(name, info["src"], enabled=True, android_drop=12)
            self.workers[name] = w
            w.start()

        self._autosave()
        self._refresh_table()

    def save_env_now(self):
        save_env_state(self.cameras)
        self.status_var.set("Guardado en .env")

    def scan_webcams_async(self):
        threading.Thread(target=self._scan_webcams, daemon=True).start()

    def _scan_webcams(self):
        self.status_var.set("Escaneando webcams…")
        added = []
        try:
            devices = discover_local_cameras(max_index=10)
            for dev in devices:
                name = (dev.get("name") or dev.get("id") or "").strip()
                src = dev.get("uri")
                if not name:
                    continue
                name = self._unique_name(name)
                if name not in self.cameras:
                    self.cameras[name] = {"src": src, "enabled": True, "status": "Parada"}
                    added.append(name)
            self._autosave()
        except Exception as e:
            self.status_var.set(f"Error: {e}")

        self._refresh_table()
        self.status_var.set("Escaneo webcams finalizado" + (f". Añadidas: {', '.join(added)}" if added else "."))

    def scan_network_async(self):
        if self._net_scan_thread and self._net_scan_thread.is_alive():
            messagebox.showinfo("Info", "Ya hay un escaneo de red en marcha")
            return
        self._net_scan_stop.clear()
        self._net_scan_thread = threading.Thread(target=self._scan_network, daemon=True)
        self._net_scan_thread.start()

    def _scan_network(self):
        def progress(done, total, found):
            self.after(0, lambda: self.status_var.set(f"Escaneando red… {done}/{total} encontradas: {found}"))

        found = scan_subnet_for_cameras(stop_flag=self._net_scan_stop, progress_cb=progress)
        added = []
        for item in found:
            name = self._unique_name(item["name"])
            src = item["src"]
            if name not in self.cameras:
                self.cameras[name] = {"src": src, "enabled": True, "status": "Parada"}
                added.append(name)

        if added:
            self._autosave()

        self.after(0, self._refresh_table)
        self.after(0, lambda: self.status_var.set("Escaneo red finalizado" + (f". Añadidas: {', '.join(added)}" if added else ".")))

    def start_all(self):
        if self.workers:
            messagebox.showinfo("Info", "Ya está en marcha")
            return
        for name, info in self.cameras.items():
            info["status"] = "Parada"
            if info.get("enabled", True):
                w = CamWorker(name, info["src"], enabled=True, android_drop=12)
                self.workers[name] = w
                w.start()
        self.status_var.set("Aplicación iniciada")
        self._refresh_table()

    def stop_all(self):
        for _, w in list(self.workers.items()):
            w.stop_and_join(timeout=1.5)
        self.workers.clear()
        for info in self.cameras.values():
            info["status"] = "Parada"
        self.status_var.set("Aplicación detenida")
        self._refresh_table()

    def _loop_preview(self):
        named = []
        for name, info in self.cameras.items():
            if name in self.workers:
                status = self.workers[name].status
                frame = self.workers[name].frame
                info["status"] = status
            else:
                status = info.get("status", "Parada")
                frame = None
            named.append((name, status, frame))

        mosaic = build_mosaic(named, tile_w=480, tile_h=270, cols=2)
        rgb = cv2.cvtColor(mosaic, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        imgtk = ImageTk.PhotoImage(pil)
        self._preview_imgtk = imgtk

        if self._preview_img_id is None:
            self._preview_img_id = self.preview_canvas.create_image(0, 0, anchor="nw", image=imgtk)
        else:
            self.preview_canvas.itemconfig(self._preview_img_id, image=imgtk)

        w, h = pil.size
        self.preview_canvas.config(scrollregion=(0, 0, w, h))

        self._refresh_table()
        self.after(150, self._loop_preview)


def main():
    app = MultiCamUI()
    app.mainloop()


if __name__ == "__main__":
    main()