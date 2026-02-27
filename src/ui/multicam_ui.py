# -*- coding: utf-8 -*-
"""
Videovigilancia - UI Multicámara (VERSIÓN INTEGRADA / SIN ZOOM)

✔ Multicámara (mosaico)
✔ Webcam / Android MJPEG / iPad RTSP
✔ Detección por Wi‑Fi (puertos 8080/8554) usando src/discovery/network_scan.py
✔ UI: diálogo para listar, probar y añadir cámaras detectadas
✔ Telegram multi-destinatario configurable desde la UI
✔ Guardado en .env
✔ Baja latencia
✔ Personas + vehículos
✔ Día / Noche
✔ Scroll horizontal debajo de los botones + Scroll vertical en previsualización
"""

import os
import cv2
import time
import threading
import math
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageTk
import numpy as np

from dotenv import load_dotenv
load_dotenv()

from src.detection.person_detector import PersonDetector
from src.alerts.telegram_alert import TelegramAlert
from src.camera.discovery import discover_local_cameras

import json
import subprocess
import requests
import qrcode

# --- Import robusto del escaneo de red (tu fichero) ---
ns_discover = None
try:
    from src.discovery.network_scan import discover_cameras as ns_discover
except Exception:
    try:
        from src.discovery.Network_scan import discover_cameras as ns_discover
    except Exception:
        ns_discover = None

# ============================================================
# ENV
# ============================================================
MULTICAM_RAW = os.getenv("MULTICAM_CONFIG", "")
DISABLED_RAW = os.getenv("MULTICAM_DISABLED", "")
YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "models/yolov8n.pt")
AUTO_SAVE_ENV = True

TELEGRAM = TelegramAlert.from_env()

# ============================================================
# ENV HELPERS
# ============================================================
def update_env_key(key, value, env_path=".env"):
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_multicam_env(raw):
    out = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = int(v) if v.strip().isdigit() else v.strip()
    return out


def parse_disabled_names(raw):
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


def save_env_state(cameras):
    cfg = {n: i["src"] for n, i in cameras.items()}
    disabled = [n for n, i in cameras.items() if not i["enabled"]]
    update_env_key("MULTICAM_CONFIG", ",".join(f"{k}={v}" for k, v in cfg.items()))
    update_env_key("MULTICAM_DISABLED", ",".join(disabled))


# ============================================================
# TELEGRAM HELPERS
# ============================================================
def load_telegram_ids_from_env():
    users = TelegramAlert.parse_ids(os.getenv("TELEGRAM_USER_CHAT_IDS", ""))
    groups = TelegramAlert.parse_ids(os.getenv("TELEGRAM_GROUP_CHAT_IDS", ""))
    return users, groups


def save_telegram_ids_to_env(users, groups):
    update_env_key("TELEGRAM_USER_CHAT_IDS", ",".join(users))
    update_env_key("TELEGRAM_GROUP_CHAT_IDS", ",".join(groups))


def send_telegram_alert(camera_name, frame, detected_type):
    global TELEGRAM
    if TELEGRAM is None:
        return

    now = datetime.now()
    stamp = now.strftime("%d/%m/%Y %H:%M:%S")

    os.makedirs("logs", exist_ok=True)
    tmp = f"logs/alert_{camera_name}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"

    ok, jpg = cv2.imencode(".jpg", frame)
    if ok:
        with open(tmp, "wb") as f:
            f.write(jpg.tobytes())

    # Brillo promedio del frame para icono día/noche
    try:
        mean_val = float(np.mean(frame))
    except Exception:
        mean_val = 128.0
    modo = "🌙" if mean_val < 45 else "☀️"

    msg = (
        f"🚨 Detección\n"
        f"📷 Cámara: {camera_name}\n"
        f"🔎 Tipo: {detected_type}\n"
        f"🕒 {stamp}\n"
        f"{modo}"
    )

    TELEGRAM.send_alert_async(msg, photo_path=tmp if ok else None)

    def cleanup():
        time.sleep(5)
        try:
            os.remove(tmp)
        except Exception:
            pass

    threading.Thread(target=cleanup, daemon=True).start()


# ============================================================
# WORKER
# ============================================================
DETECT_LOCK = threading.Lock()


class CamWorker(threading.Thread):
    def __init__(self, name, src):
        super().__init__(daemon=True)
        self.name = name
        self.src = src
        self.stop_evt = threading.Event()
        self.cap = None
        self.frame = None
        self.status = "Parada"
        self.last_brightness = None
        self._last_detect = 0
        self._last_frame_ts = time.time()

        self.detector = PersonDetector(
            model_path=YOLO_MODEL_PATH,
            confidence_threshold=0.35,
            min_persistence_frames=3,
            cooldown_seconds=30,
        )

    def stop_and_join(self):
        self.stop_evt.set()
        self.join(timeout=1.5)

    def _open(self):
        src = self.src
        if isinstance(src, str) and src.isdigit():
            src = int(src)

        if isinstance(src, str) and (src.startswith("rtsp://") or src.startswith("http://") or src.startswith("https://")):
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            try:
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2500)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2500)
            except Exception:
                pass
        else:
            self.cap = cv2.VideoCapture(src)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            
    def run(self):
        # Asegura que existe el timestamp de último frame (por si no lo pusiste en __init__)
        if not hasattr(self, "_last_frame_ts"):
            self._last_frame_ts = time.time()

        # Abre captura inicial
        self._open()
        self._last_frame_ts = time.time()

        while not self.stop_evt.is_set():
            frame = None

            # 1) Leer SIEMPRE el frame más reciente (descartar antiguos)
            try:
                # grab() descarta frames sin decodificar (más rápido que read)
                for _ in range(10):
                    if self.stop_evt.is_set():
                        break
                    if not self.cap or not self.cap.grab():
                        break

                if self.stop_evt.is_set():
                    break

                if self.cap:
                    ok, tmp = self.cap.retrieve()
                    if ok:
                        frame = tmp
            except Exception:
                frame = None

            # 2) Si no hay frame -> marca sin señal y aplica watchdog de reconexión
            if frame is None:
                self.status = "Sin señal"

                # Watchdog: si llevamos mucho sin frames, reabrir stream
                if time.time() - self._last_frame_ts > 4.0:
                    try:
                        if self.cap:
                            self.cap.release()
                    except Exception:
                        pass

                    # Pequeña pausa antes de reabrir
                    time.sleep(0.5)

                    # Reintento de apertura
                    try:
                        self._open()
                    except Exception:
                        pass

                    self._last_frame_ts = time.time()

                # Evita bucle agresivo sin señal
                time.sleep(0.10)
                continue

            # 3) Tenemos frame: actualizar timestamp y estado
            self._last_frame_ts = time.time()
            self.status = "Activa"

            confirmed = False
            annotated = frame

            # 4) Detección con throttle y LOCK NO BLOQUEANTE (evita lag entre cámaras)
            now = time.time()
            if now - self._last_detect > 0.6:  # ajusta 0.6..1.2 según CPU/cámaras
                self._last_detect = now

                acquired = DETECT_LOCK.acquire(blocking=False)
                if acquired:
                    try:
                        confirmed, annotated = self.detector.detect(frame)
                        self.last_brightness = getattr(self.detector, "last_brightness", None)
                    finally:
                        DETECT_LOCK.release()
                else:
                    # Si otra cámara está detectando, no bloqueamos captura
                    confirmed, annotated = False, frame
                    # last_brightness se mantiene con el último valor válido

            # 5) Publicar frame para UI
            self.frame = annotated

            # 6) Enviar alerta si confirmado
            if confirmed:
                send_telegram_alert(
                    self.name,
                    annotated,
                    getattr(self.detector, "last_detected_type", "OBJETO"),
                )

            # Pequeño sleep opcional para no ir a tope si todo va muy rápido
            # (normalmente no hace falta, pero ayuda en streams que entregan frames muy rápido)
            time.sleep(0.001)

        # Cleanup al salir
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass

# ============================================================
# MOSAICO
# ============================================================
def build_mosaic(frames, cols=2, tile_w=640, tile_h=360):
    tiles = []
    for name, status, frame, brightness in frames:
        if frame is None:
            img = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
            cv2.putText(
                img, "SIN SEÑAL", (int(tile_w * 0.25), int(tile_h * 0.5)),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2
            )
        else:
            img = cv2.resize(frame, (tile_w, tile_h))

        cv2.putText(img, name, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        if brightness is not None:
            icon = "🌙" if brightness < 45 else "☀️"
            cv2.putText(img, icon, (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        tiles.append(img)

    if not tiles:
        return None

    rem = len(tiles) % cols
    if rem:
        for _ in range(cols - rem):
            tiles.append(np.zeros((tile_h, tile_w, 3), dtype=np.uint8))

    rows = []
    for i in range(0, len(tiles), cols):
        rows.append(np.hstack(tiles[i:i + cols]))

    return np.vstack(rows)


# ============================================================
# UI
# ============================================================
class MultiCamUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Videovigilancia - UI Multicámara")
        self.geometry("1280x800")

        self.cameras = {}
        self.workers = {}
        self._pending_refresh = False

        disabled = parse_disabled_names(DISABLED_RAW)
        for name, src in parse_multicam_env(MULTICAM_RAW).items():
            self.cameras[name] = {
                "src": src,
                "enabled": name not in disabled,
                "status": "Parada",
            }

        self._build_ui()
        self._refresh_table()
        self.after(150, self._loop_preview)

    def _build_ui(self):
        
        top_area = ttk.Frame(self)
        top_area.pack(fill=tk.BOTH, expand=False)

        self.top_canvas = tk.Canvas(top_area, highlightthickness=0)
        self.top_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_vscroll = ttk.Scrollbar(top_area, orient="vertical", command=self.top_canvas.yview)
        top_vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.top_canvas.configure(yscrollcommand=top_vscroll.set)

        # Frame real dentro del canvas (aquí meteremos toolbar + tabla)
        self.top_content = ttk.Frame(self.top_canvas)
        self.top_window_id = self.top_canvas.create_window((0, 0), window=self.top_content, anchor="nw")

        # --- Toolbar superior (BOTONES) ---
        toolbar = ttk.Frame(self.top_content)
        toolbar.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(toolbar, text="Emparejar móvil (QR)", command=self._open_pairing_qr).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Telegram", command=self.open_telegram_config).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Probar TG (texto)", command=self._on_test_telegram_text).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Probar TG (foto)", command=self._on_test_telegram_photo).pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Escanear webcams", command=self._scan_webcams).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Detectar cámaras (Wi‑Fi)", command=self._open_wifi_discovery_dialog).pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Añadir", command=self.add_cam).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Eliminar", command=self.delete_cam).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Iniciar", command=self.start_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Parar", command=self.stop_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Salir", command=self.destroy).pack(side=tk.LEFT, padx=4)

        # --- Scroll horizontal justo debajo de los botones (como pediste) ---
        hscroll_bar = ttk.Frame(self.top_content)
        hscroll_bar.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.h_scroll = ttk.Scrollbar(hscroll_bar, orient="horizontal")
        self.h_scroll.pack(fill=tk.X)

        # --- Tabla de cámaras ---
        mid = ttk.Frame(self.top_content)
        mid.pack(fill=tk.X, padx=8, pady=(0, 6))
        cols = ("enabled", "name", "src", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=6)
        for c in cols:
            self.tree.heading(c, text=c)
        self.tree.pack(fill=tk.X)

        # --- Mantener scrollregion del top_canvas y ajustar anchura del frame interior ---
        def _top_on_configure(_event=None):
            self.top_canvas.configure(scrollregion=self.top_canvas.bbox("all"))
            # Asegura que el frame interior ocupe el ancho del canvas (para que los botones no se "corten")
            self.top_canvas.itemconfigure(self.top_window_id, width=self.top_canvas.winfo_width())

        self.top_content.bind("<Configure>", _top_on_configure)
        self.top_canvas.bind("<Configure>", _top_on_configure)

        # (Opcional) Scroll con rueda del ratón sobre la zona superior
        def _top_wheel(event):
            # En macOS event.delta suele ser pequeño; en Windows grande
            delta = event.delta
            step = -1 if delta > 0 else 1
            self.top_canvas.yview_scroll(step, "units")

        self.top_canvas.bind_all("<MouseWheel>", _top_wheel)

        # Preview con scroll
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.preview_canvas = tk.Canvas(preview_frame, bg="black")
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_canvas.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.preview_canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=self.h_scroll.set)
        self.h_scroll.configure(command=self.preview_canvas.xview)

        self.preview_canvas.bind("<Configure>", lambda e: self._request_refresh())
        self._bind_mousewheel(self.preview_canvas)

    # ---------------- TELEGRAM UI ----------------
    def open_telegram_config(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            messagebox.showwarning("Telegram", "Falta TELEGRAM_BOT_TOKEN en .env")
            return

        users, groups = load_telegram_ids_from_env()

        win = tk.Toplevel(self)
        win.title("Configuración Telegram - Destinatarios")
        win.geometry("820x460")
        win.transient(self)
        win.grab_set()

        info = (
            "Las alertas se enviarán a TODOS los destinatarios configurados.\n\n"
            "• Usuarios: deben haber escrito /start al bot\n"
            "• Grupos/Canales: el bot debe estar añadido\n\n"
            "Puedes importar chats automáticamente desde getUpdates."
        )
        ttk.Label(win, text=info, justify="left", wraplength=780).pack(padx=12, pady=10, anchor="w")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        lf_users = ttk.LabelFrame(container, text="Usuarios")
        lf_users.pack(side=tk.LEFT, fill="both", expand=True, padx=(0, 6))
        lb_users = tk.Listbox(lf_users)
        lb_users.pack(fill="both", expand=True, padx=6, pady=6)
        for u in users:
            lb_users.insert(tk.END, u)

        lf_groups = ttk.LabelFrame(container, text="Grupos / Canales")
        lf_groups.pack(side=tk.LEFT, fill="both", expand=True, padx=(6, 0))
        lb_groups = tk.Listbox(lf_groups)
        lb_groups.pack(fill="both", expand=True, padx=6, pady=6)
        for g in groups:
            lb_groups.insert(tk.END, g)

        actions = ttk.Frame(win)
        actions.pack(fill="x", padx=12, pady=10)

        def add_destination(kind):
            chat_id = simpledialog.askstring("Añadir destinatario", "Pega el chat_id:", parent=win)
            if not chat_id:
                return
            chat_id = chat_id.strip()
            if kind == "user":
                if chat_id not in lb_users.get(0, tk.END):
                    lb_users.insert(tk.END, chat_id)
            else:
                if chat_id not in lb_groups.get(0, tk.END):
                    lb_groups.insert(tk.END, chat_id)

        def remove_selected(lb):
            for i in reversed(lb.curselection()):
                lb.delete(i)

        def import_updates():
            try:
                tg = TelegramAlert(token, [], [])
                data = tg.get_updates()

                for upd in data.get("result", []):
                    msg = upd.get("message") or upd.get("channel_post")
                    if not msg:
                        continue
                    chat = msg.get("chat", {})
                    cid = str(chat.get("id"))
                    ctype = chat.get("type")

                    if ctype in ("group", "supergroup", "channel") or cid.startswith("-"):
                        if cid not in lb_groups.get(0, tk.END):
                            lb_groups.insert(tk.END, cid)
                    else:
                        if cid not in lb_users.get(0, tk.END):
                            lb_users.insert(tk.END, cid)

                messagebox.showinfo("Telegram", "Importación completada")
            except Exception as e:
                messagebox.showerror("Telegram", str(e))

        def save_and_close():
            users_new = list(lb_users.get(0, tk.END))
            groups_new = list(lb_groups.get(0, tk.END))

            save_telegram_ids_to_env(users_new, groups_new)

            load_dotenv(".env", override=True)
            global TELEGRAM
            TELEGRAM = TelegramAlert.from_env()

            messagebox.showinfo("Telegram", "Destinatarios guardados correctamente")
            win.destroy()

        ttk.Button(actions, text="Añadir usuario", command=lambda: add_destination("user")).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Quitar usuario", command=lambda: remove_selected(lb_users)).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Añadir grupo", command=lambda: add_destination("group")).pack(side=tk.LEFT, padx=12)
        ttk.Button(actions, text="Quitar grupo", command=lambda: remove_selected(lb_groups)).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Importar getUpdates", command=import_updates).pack(side=tk.LEFT, padx=12)
        ttk.Button(actions, text="Guardar y cerrar", command=save_and_close).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    # ---------------- CÁMARAS ----------------
    def add_cam(self):
        name = simpledialog.askstring("Nombre", "Nombre cámara:")
        src = simpledialog.askstring("Fuente", "Índice o URL:")
        if name and src:
            self.cameras[name] = {"src": src, "enabled": True, "status": "Parada"}
            save_env_state(self.cameras)
            self._refresh_table()
            self._request_refresh()

    def delete_cam(self):
        sel = self.tree.selection()
        if sel:
            del self.cameras[sel[0]]
            save_env_state(self.cameras)
            self._refresh_table()
            self._request_refresh()

    def _scan_webcams(self):
        cams = discover_local_cameras()
        for cam in cams:
            name = cam["name"]
            src = cam["uri"]
            if name not in self.cameras:
                self.cameras[name] = {"src": src, "enabled": True, "status": "Parada"}
        save_env_state(self.cameras)
        self._refresh_table()
        self._request_refresh()
        messagebox.showinfo("Webcams", f"Detectadas {len(cams)} webcam(s)")

    def _get_tailscale_ip(self):
        """
        Devuelve la IP de Tailscale (100.x) para construir server_url.
        Requiere que el comando 'tailscale' exista en PATH. [1](https://www.digitalsamba.com/blog/webrtc-security)
        """
        try:
            out = subprocess.check_output(["tailscale", "ip", "-4"], text=True).strip()
            # Puede devolver varias líneas; usamos la primera no vacía
            for line in out.splitlines():
                line = line.strip()
                if line:
                    return line
        except Exception:
            return None
        return None


    def _open_pairing_qr(self):
        """
        1) Llama al servidor: POST /api/pair/request -> pair_code (6 dígitos) + expires_at
        2) Genera un QR con payload JSON: server_url + pair_code + expires_at
        3) Muestra ventana con QR + botón copiar + regenerar
        """
        # --- Determinar server_url (solo Tailnet) ---
        ts_ip = self._get_tailscale_ip()
        if not ts_ip:
            messagebox.showerror(
                "Pairing QR",
                "No se pudo obtener la IP de Tailscale.\n"
                "Comprueba que Tailscale está conectado y que el comando 'tailscale ip -4' funciona."
            )
            return

        server_url = f"http://{ts_ip}:8443"  # MVP (luego pasaremos a https)
        endpoint = f"{server_url}/api/pair/request"

        # --- Pedir pair_code al servidor ---
        try:
            r = requests.post(endpoint, timeout=5)
            r.raise_for_status()
            data = r.json()
            pair_code = str(data.get("pair_code", "")).strip()
            expires_at = int(data.get("expires_at", 0))
            if not pair_code or len(pair_code) != 6:
                raise ValueError("Respuesta inválida: pair_code no es de 6 dígitos")
        except Exception as e:
            messagebox.showerror("Pairing QR", f"No se pudo generar el código de emparejado:\n{e}")
            return

        payload = {
            "server_url": server_url,
            "pair_code": pair_code,
            "expires_at": expires_at,
            "api_version": "0.1.0",
        }

        payload_str = json.dumps(payload, ensure_ascii=False)

        # --- Generar QR ---
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(payload_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # --- UI: Ventana QR ---
        win = tk.Toplevel(self)
        win.title("Emparejar móvil (QR)")
        win.geometry("420x520")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="Escanea este QR con la App móvil", font=("Arial", 13, "bold")).pack(pady=(12, 6))

        # Convertir a ImageTk
        imgtk = ImageTk.PhotoImage(img)
        lbl_img = ttk.Label(win, image=imgtk)
        lbl_img.image = imgtk
        lbl_img.pack(pady=8)

        # Texto informativo
        info = ttk.Label(
            win,
            text=f"Servidor: {server_url}\nCódigo: {pair_code}\nCaduca en ~5 min",
            justify="center"
        )
        info.pack(pady=(6, 8))

    # Copiar payload al portapapeles (por si quieres pegarlo en pruebas)
    def copy_payload():
        self.clipboard_clear()
        self.clipboard_append(payload_str)
        messagebox.showinfo("Pairing QR", "Payload copiado al portapapeles")

    # Regenerar QR
    def regenerate():
            try:
                win.destroy()
            except Exception:
                pass
            self.after(50, self._open_pairing_qr)

            actions = ttk.Frame(win)
            actions.pack(fill=tk.X, pady=10, padx=10)

            ttk.Button(actions, text="Copiar payload", command=copy_payload).pack(side=tk.LEFT, padx=4)
            ttk.Button(actions, text="Regenerar", command=regenerate).pack(side=tk.LEFT, padx=4)
            ttk.Button(actions, text="Cerrar", command=win.destroy).pack(side=tk.RIGHT, padx=4)


    # --- Diálogo Wi‑Fi ---
    def _open_wifi_discovery_dialog(self):
        if ns_discover is None:
            messagebox.showwarning(
                "Detección Wi‑Fi",
                "No se encuentra src/discovery/network_scan.py o no expone discover_cameras()."
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Detección de cámaras en Wi‑Fi")
        dlg.geometry("980x520")
        dlg.transient(self)
        dlg.grab_set()

        top = ttk.Frame(dlg)
        top.pack(fill=tk.X, padx=10, pady=8)

        ttk.Label(top, text="Subred (opcional, ej. 192.168.1.0/24):").pack(side=tk.LEFT, padx=(0, 6))
        sub_var = tk.StringVar(value="")
        ttk.Entry(top, textvariable=sub_var, width=22).pack(side=tk.LEFT, padx=(0, 10))

        status_lbl = ttk.Label(top, text="Listo")
        status_lbl.pack(side=tk.LEFT, padx=(12, 8))

        def set_status(txt):
            status_lbl.config(text=txt)
            dlg.update_idletasks()

        cols = ("ip", "puertos", "url")
        tree = ttk.Treeview(dlg, columns=cols, show="headings", height=14)
        tree.heading("ip", text="IP")
        tree.heading("puertos", text="Puertos")
        tree.heading("url", text="Candidata (doble clic para probar)")
        tree.column("ip", width=140, anchor="center")
        tree.column("puertos", width=180, anchor="center")
        tree.column("url", width=600, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        actions = ttk.Frame(dlg)
        actions.pack(fill=tk.X, padx=10, pady=8)

        scan_btn = ttk.Button(actions, text="Escanear")
        test_btn = ttk.Button(actions, text="Probar URL seleccionada")
        add_btn = ttk.Button(actions, text="Añadir a cámaras")
        ttk.Button(actions, text="Cerrar", command=dlg.destroy).pack(side=tk.RIGHT, padx=4)

        scan_btn.pack(side=tk.LEFT, padx=4)
        test_btn.pack(side=tk.LEFT, padx=12)
        add_btn.pack(side=tk.LEFT, padx=12)

        results_cache = []

        def do_scan():
            scan_btn.config(state="disabled")
            test_btn.config(state="disabled")
            add_btn.config(state="disabled")
            tree.delete(*tree.get_children())

            hint = sub_var.get().strip() or None
            set_status("Escaneando red… (puede tardar unos segundos)")

            def worker():
                nonlocal results_cache
                try:
                    results = ns_discover(auto_iface=True, cidr_hint=hint)
                except TypeError:
                    results = ns_discover(hint) if hint else ns_discover()
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Detección Wi‑Fi", str(e)))
                    results = []

                def fill_table():
                    tree.delete(*tree.get_children())
                    results_cache = results or []

                    # ✅ FILTRO: solo Android (8080) e iPad (8554)
                    shown = 0
                    for cam in results_cache:
                        ip = cam.get("ip", "")
                        ports = cam.get("ports", []) or []
                        if 8080 not in ports and 8554 not in ports:
                            continue
                        puertos = ",".join(map(str, ports))
                        for url in (cam.get("candidates") or [])[:3]:
                            tree.insert("", tk.END, values=(ip, puertos, url))
                            shown += 1

                    set_status(f"Detectadas {shown} candidata(s) (Android 8080 / iPad 8554)")
                    scan_btn.config(state="normal")
                    test_btn.config(state="normal")
                    add_btn.config(state="normal")

                self.after(0, fill_table)

            threading.Thread(target=worker, daemon=True).start()

        def get_selected_url():
            sel = tree.selection()
            if not sel:
                return None, None
            vals = tree.item(sel[0], "values")
            if len(vals) < 3:
                return None, None
            return vals[0], vals[2]

        def test_url(url):
            # Probar 1 frame (sin congelar demasiado)
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG) if url.startswith("rtsp://") else cv2.VideoCapture(url)
            if not cap.isOpened():
                cap.release()
                return False, "no-open"
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, _ = cap.read()
            cap.release()
            return (True, "ok") if ok else (False, "no-frame")

        def do_test():
            ip, url = get_selected_url()
            if not url:
                messagebox.showinfo("Probar", "Selecciona una fila con URL candidata.")
                return
            set_status(f"Probando {url} …")

            def worker():
                ok, st = test_url(url)

                def done():
                    set_status("Listo")
                    if ok:
                        messagebox.showinfo("Probar", f"✅ OK: {url}")
                    else:
                        messagebox.showwarning("Probar", f"❌ Fallo ({st}): {url}")

                self.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        def do_add():
            ip, url = get_selected_url()
            if not url:
                messagebox.showinfo("Añadir", "Selecciona una fila con URL candidata.")
                return

            base = "RTSP" if url.startswith("rtsp://") else "HTTP"
            name_base = f"{base}-{ip}"
            name = name_base
            k = 1
            while name in self.cameras:
                k += 1
                name = f"{name_base}-{k}"

            self.cameras[name] = {"src": url, "enabled": True, "status": "Parada"}
            save_env_state(self.cameras)
            self._refresh_table()
            self._request_refresh()
            messagebox.showinfo("Añadir", f"Añadida cámara '{name}' con fuente:\n{url}")

        scan_btn.configure(command=do_scan)
        test_btn.configure(command=do_test)
        add_btn.configure(command=do_add)

        tree.bind("<Double-1>", lambda _e: do_test())

        # ✅ Mejor: NO escanear automáticamente al abrir (evita esperas)
        # do_scan()

    def start_all(self):
        for name, info in self.cameras.items():
            if not info.get("enabled", True):
                continue
            if name in self.workers:
                continue
            w = CamWorker(name, info["src"])
            self.workers[name] = w
            w.start()

    def stop_all(self):
        for w in list(self.workers.values()):
            w.stop_and_join()
        self.workers.clear()

    def _refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for n, i in self.cameras.items():
            self.tree.insert("", tk.END, iid=n, values=(
                "Sí" if i.get("enabled", True) else "No",
                n,
                i.get("src", ""),
                i.get("status", ""),
            ))

    # ---------------- PREVISUALIZACIÓN + MOSAICO ----------------
    def _bind_mousewheel(self, widget):
        def _on_wheel(event):
            delta = event.delta
            if event.state & 0x0001:  # Shift horizontal
                self.preview_canvas.xview_scroll(-1 if delta > 0 else 1, "units")
            else:
                self.preview_canvas.yview_scroll(-1 if delta > 0 else 1, "units")

        widget.bind_all("<MouseWheel>", _on_wheel)
        widget.bind_all("<Shift-MouseWheel>", _on_wheel)
        widget.bind_all("<Button-4>", lambda e: self.preview_canvas.yview_scroll(-1, "units"))
        widget.bind_all("<Button-5>", lambda e: self.preview_canvas.yview_scroll(1, "units"))

    def _choose_cols(self, count: int) -> int:
        if count <= 1: return 1
        if count <= 2: return 2
        if count <= 4: return 2
        if count <= 6: return 3
        if count <= 9: return 3
        if count <= 12: return 4
        return 4

    def _compute_tile_size(self, count: int, cols: int):
        """
        SIN ZOOM: nunca hace upscale; solo reduce si hace falta para encajar.
        """
        rows = max(1, math.ceil(count / max(1, cols)))
        vw = max(400, self.preview_canvas.winfo_width())
        vh = max(300, self.preview_canvas.winfo_height())

        base_w = 640
        base_h = int(base_w * 9 / 16)
        tw, th = base_w, base_h

        total_w = cols * tw
        total_h = rows * th
        scale_w = vw / total_w if total_w > 0 else 1.0
        scale_h = vh / total_h if total_h > 0 else 1.0
        scale = min(1.0, scale_w, scale_h)

        tw = max(240, int(tw * scale))
        th = max(135, int(th * scale))
        return tw, th, rows

    def _request_refresh(self):
        if self._pending_refresh:
            return
        self._pending_refresh = True
        self.after(60, self._loop_preview)

    def _loop_preview(self):
        self._pending_refresh = False

        frames = []
        for name in self.cameras:
            if name in self.workers:
                w = self.workers[name]
                frames.append((name, w.status, w.frame, w.last_brightness))

        if not frames:
            self.preview_canvas.delete("all")
            self.preview_canvas.configure(scrollregion=(0, 0, 0, 0))
            self.after(150, self._loop_preview)
            return

        count = len(frames)
        cols = self._choose_cols(count)
        tile_w, tile_h, _rows = self._compute_tile_size(count, cols)

        mosaic = build_mosaic(frames, cols=cols, tile_w=tile_w, tile_h=tile_h)
        if mosaic is None:
            self.after(150, self._loop_preview)
            return

        rgb = cv2.cvtColor(mosaic, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))

        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=imgtk)
        self.preview_canvas.image = imgtk

        h, w = mosaic.shape[:2]
        self.preview_canvas.configure(scrollregion=(0, 0, w, h))

        self.after(150, self._loop_preview)

    # ---------------- PRUEBAS TELEGRAM (UI) ----------------
    def _on_test_telegram_text(self):
        global TELEGRAM
        if TELEGRAM is None:
            messagebox.showwarning("Telegram", "Telegram no está configurado o falta token.")
            return
        ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        msg = f"🔔 Prueba de Telegram | {ts}"
        threading.Thread(target=lambda: TELEGRAM.send_alert_async(msg), daemon=True).start()
        messagebox.showinfo("Telegram", "Mensaje de prueba enviado (revisa los destinos configurados).")

    def _on_test_telegram_photo(self):
        global TELEGRAM
        if TELEGRAM is None:
            messagebox.showwarning("Telegram", "Telegram no está configurado o falta token.")
            return
        path = filedialog.askopenfilename(
            title="Selecciona una imagen",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.bmp *.webp"), ("Todos", "*.*")],
        )
        if not path:
            return
        ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        caption = f"🔔 Prueba de foto | {ts}"
        threading.Thread(target=lambda: TELEGRAM.send_alert_async(caption, photo_path=path), daemon=True).start()
        messagebox.showinfo("Telegram", "Foto de prueba enviada (revisa los destinos configurados).")


def main():
    app = MultiCamUI()
    app.mainloop()


if __name__ == "__main__":
    main()