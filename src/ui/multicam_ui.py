# -*- coding: utf-8 -*-
"""
Videovigilancia - UI Multicámara (VERSIÓN DEFINITIVA)

✔ Multicámara real (mosaico)
✔ Webcam / Android MJPEG / iPad RTSP
✔ Escaneo de webcams y red
✔ Telegram multi-destinatario configurable desde la UI
✔ Guardado en .env
✔ Baja latencia
✔ Personas + vehículos
✔ Día / Noche
✔ Scroll en previsualización + Zoom
"""

import os
import cv2
import time
import threading
import ipaddress
import socket
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

    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
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

        if isinstance(src, str) and src.startswith("rtsp://"):
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            # Reduce buffering/latencia
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            try:
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
            except Exception:
                pass
        else:
            self.cap = cv2.VideoCapture(src)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def run(self):
        self._open()
        while not self.stop_evt.is_set():
            frame = None
            # Lee varios frames para vaciar buffer y reducir lag
            for _ in range(5):
                ok, tmp = self.cap.read()
                if ok:
                    frame = tmp

            if frame is None:
                self.status = "Sin señal"
                time.sleep(0.2)
                continue

            self.status = "Activa"
            confirmed = False
            annotated = frame

            now = time.time()
            if now - self._last_detect > 0.4:
                self._last_detect = now
                with DETECT_LOCK:
                    confirmed, annotated = self.detector.detect(frame)
                self.last_brightness = getattr(self.detector, "last_brightness", None)

            self.frame = annotated

            if confirmed:
                send_telegram_alert(
                    self.name,
                    annotated,
                    getattr(self.detector, "last_detected_type", "OBJETO"),
                )

        if self.cap:
            self.cap.release()


# ============================================================
# MOSAICO
# ============================================================
def build_mosaic(frames, cols=2, tile_w=640, tile_h=360):
    """
    Construye un mosaico (sin separaciones) a partir de frames BGR.
    frames: lista de tuplas (name, status, frame, brightness)
    """
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

        # Etiqueta superior izquierda con el nombre
        cv2.putText(
            img, name, (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2
        )

        # Indicador día/noche si hay brillo calculado
        if brightness is not None:
            icon = "🌙" if brightness < 45 else "☀️"
            cv2.putText(
                img, icon, (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2
            )

        tiles.append(img)

    if not tiles:
        return None

    # 🔧 Rellenar la última fila con tiles negros hasta completar 'cols'
    rem = len(tiles) % cols
    if rem:
        pad = cols - rem
        for _ in range(pad):
            tiles.append(np.zeros((tile_h, tile_w, 3), dtype=np.uint8))

    rows = []
    for i in range(0, len(tiles), cols):
        row = np.hstack(tiles[i:i + cols])
        rows.append(row)

    mosaic = np.vstack(rows)
    return mosaic


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

        # Zoom del mosaico en %
        self.zoom_pct = tk.IntVar(value=100)

        # ✅ Inicializa el flag ANTES de cualquier callback de zoom
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

    # ---------------- UI ----------------
    def _build_ui(self):
        # Toolbar superior
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(toolbar, text="Telegram", command=self.open_telegram_config).pack(
            side=tk.LEFT, padx=4
        )
        # Botones de prueba de Telegram
        ttk.Button(toolbar, text="Probar TG (texto)", command=self._on_test_telegram_text).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Probar TG (foto)", command=self._on_test_telegram_photo).pack(
            side=tk.LEFT, padx=4
        )

        # Zoom (crear label antes del scale para evitar callbacks prematuros sin label)
        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT, padx=(16, 4))
        self.zoom_label = ttk.Label(toolbar, text=f"{self.zoom_pct.get()}%")
        self.zoom_label.pack(side=tk.LEFT, padx=(4, 12))
        zoom_scale = ttk.Scale(
            toolbar, from_=50, to=200,
            orient="horizontal",
            command=self._on_zoom_change
        )
        zoom_scale.set(self.zoom_pct.get())
        zoom_scale.pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Escanear webcams", command=self._scan_webcams).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Escanear red", command=self._scan_network).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Button(toolbar, text="Añadir", command=self.add_cam).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Eliminar", command=self.delete_cam).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Button(toolbar, text="Iniciar", command=self.start_all).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Parar", command=self.stop_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Salir", command=self.destroy).pack(side=tk.LEFT, padx=4)

        # Tabla de cámaras
        mid = ttk.Frame(self)
        mid.pack(fill=tk.X, padx=8)
        cols = ("enabled", "name", "src", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=6)
        for c in cols:
            self.tree.heading(c, text=c)
        self.tree.pack(fill=tk.X)

        # --- Zona de previsualización con scroll ---
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas con barras de scroll
        self.preview_canvas = tk.Canvas(preview_frame, bg="black")
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        v_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_canvas.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.preview_canvas.xview)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.preview_canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Enlaza redimensionamiento para refrescar
        self.preview_canvas.bind("<Configure>", lambda e: self._request_refresh())
        # Rueda del ratón (scroll vertical) y Shift+Rueda (horizontal)
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
        ttk.Label(win, text=info, justify="left", wraplength=780).pack(
            padx=12, pady=10, anchor="w"
        )

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

            # 🔥 Recargar env en memoria y re-crear cliente global de Telegram
            load_dotenv(".env", override=True)
            global TELEGRAM
            TELEGRAM = TelegramAlert.from_env()

            messagebox.showinfo("Telegram", "Destinatarios guardados correctamente")
            win.destroy()

        # Botonera acciones
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

    def _scan_network(self):
        ip = socket.gethostbyname(socket.gethostname())
        net = ipaddress.ip_network(ip + "/24", strict=False)

        found = 0
        for h in net.hosts():
            host = str(h)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            try:
                if s.connect_ex((host, 8080)) == 0:
                    self.cameras[f"Android-{host}"] = {
                        "src": f"http://{host}:8080/video",
                        "enabled": True,
                        "status": "Parada",
                    }
                    found += 1
                elif s.connect_ex((host, 8554)) == 0:
                    self.cameras[f"RTSP-{host}"] = {
                        "src": f"rtsp://{host}:8554/stream",
                        "enabled": True,
                        "status": "Parada",
                    }
                    found += 1
            finally:
                s.close()

        save_env_state(self.cameras)
        self._refresh_table()
        self._request_refresh()
        messagebox.showinfo("Red", f"Detectadas {found} cámara(s) en red")

    def start_all(self):
        for name, info in self.cameras.items():
            if info["enabled"]:
                w = CamWorker(name, info["src"])
                self.workers[name] = w
                w.start()

    def stop_all(self):
        for w in self.workers.values():
            w.stop_and_join()
        self.workers.clear()

    def _refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for n, i in self.cameras.items():
            self.tree.insert("", tk.END, iid=n, values=(
                "Sí" if i["enabled"] else "No",
                n,
                i["src"],
                i["status"],
            ))

    # ---------------- PREVISUALIZACIÓN + MOSAICO ----------------
    def _on_zoom_change(self, _val):
        # Actualiza etiqueta y refresca preview
        try:
            val = int(float(_val))
        except Exception:
            val = 100
        self.zoom_pct.set(val)
        if hasattr(self, "zoom_label"):
            self.zoom_label.configure(text=f"{val}%")
        self._request_refresh()

    def _bind_mousewheel(self, widget):
        # Mac / Windows wheel
        def _on_wheel(event):
            delta = event.delta
            if event.state & 0x0001:  # Shift para horizontal
                self.preview_canvas.xview_scroll(-1 if delta > 0 else 1, "units")
            else:
                self.preview_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
        widget.bind_all("<MouseWheel>", _on_wheel)       # Windows/macOS
        widget.bind_all("<Shift-MouseWheel>", _on_wheel)

        # Soporte básico para Linux (Button-4/5)
        widget.bind_all("<Button-4>", lambda e: self.preview_canvas.yview_scroll(-1, "units"))
        widget.bind_all("<Button-5>", lambda e: self.preview_canvas.yview_scroll(1, "units"))

    def _choose_cols(self, count: int) -> int:
        if count <= 1: return 1
        if count <= 2: return 2
        if count <= 4: return 2
        if count <= 6: return 3
        if count <= 9: return 3
        if count <= 12: return 4
        return 4  # puedes subir a 5 si sueles tener >12

    def _compute_tile_size(self, count: int, cols: int):
        """Calcula el tamaño de los azulejos (16:9) en función del viewport y del zoom."""
        rows = max(1, math.ceil(count / max(1, cols)))
        # Dimensiones del viewport actuales (si aún no están calculadas, usa defaults)
        vw = max(400, self.preview_canvas.winfo_width())
        vh = max(300, self.preview_canvas.winfo_height())

        # Base (16:9) y zoom
        base_w = 640
        base_h = int(base_w * 9 / 16)
        zoom = max(0.5, min(2.0, self.zoom_pct.get() / 100.0))
        tw = int(base_w * zoom)
        th = int(base_h * zoom)

        # Ajusta para intentar encajar en viewport sin ampliar
        total_w = cols * tw
        total_h = rows * th
        scale_w = vw / total_w if total_w > 0 else 1.0
        scale_h = vh / total_h if total_h > 0 else 1.0
        scale = min(1.0, scale_w, scale_h)

        tw = max(240, int(tw * scale))
        th = max(135, int(th * scale))
        return tw, th, rows

    def _request_refresh(self):
        """Agrupa varias solicitudes de refresco para evitar repintados excesivos."""
        # ✅ Blindaje: si aún no existe, inicializa el flag
        if not hasattr(self, "_pending_refresh"):
            self._pending_refresh = False
        if self._pending_refresh:
            return
        self._pending_refresh = True
        self.after(60, self._loop_preview)  # refresco pronto

    def _loop_preview(self):
        self._pending_refresh = False

        frames = []
        for name, info in self.cameras.items():
            if name in self.workers:
                w = self.workers[name]
                frames.append((name, w.status, w.frame, w.last_brightness))

        count = len(frames)
        if count == 0:
            # Limpia lienzo si no hay frames
            self.preview_canvas.delete("all")
            self.preview_canvas.configure(scrollregion=(0, 0, 0, 0))
            # Mantener ciclo vivo
            self.after(150, self._loop_preview)
            return

        cols = self._choose_cols(count)
        tile_w, tile_h, rows = self._compute_tile_size(count, cols)

        mosaic = build_mosaic(frames, cols=cols, tile_w=tile_w, tile_h=tile_h)
        if mosaic is None:
            self.after(150, self._loop_preview)
            return

        # Convertir a imagen Tk
        rgb = cv2.cvtColor(mosaic, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))

        # Limpiar y dibujar en (0,0) anclado arriba-izquierda
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=imgtk)
        # Guardar referencia para evitar GC
        self.preview_canvas.image = imgtk

        # Configurar región de scroll según tamaño del mosaico
        h, w = mosaic.shape[:2]
        self.preview_canvas.configure(scrollregion=(0, 0, w, h))

        # Mantener el refresco continuo
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


# ============================================================
def main():
    app = MultiCamUI()
    app.mainloop()


if __name__ == "__main__":
    main()