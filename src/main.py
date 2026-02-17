"""
Aplicación principal de videovigilancia
Integra captura de video, detección de movimiento y alertas
"""

import sys
import cv2
import logging
import time
from pathlib import Path

# Agregar el directorio src al path
sys.path.insert(0, str(Path(__file__).parent))

from camera.camera_manager import CameraManager
#from motion.motion_detector import MotionDetector
from detection.person_detector import PersonDetector
from alerts.telegram_alert import TelegramAlert
from utils.logger import setup_logger
from config import (
    CAMERA_CONFIG, MOTION_CONFIG, TELEGRAM_CONFIG, 
    TWILIO_CONFIG, LOGGING_CONFIG, RECORDING_CONFIG
)


class VideoSurveillanceApp:
    """
    Aplicación principal de videovigilancia.
    Captura video, detecta movimiento y envía alertas.
    """
    
    def __init__(self):
        """Inicializa la aplicación."""
        self.logger = setup_logger(__name__, logging.INFO)
        self.logger.info("=" * 60)
        self.logger.info("Iniciando aplicación de videovigilancia")
        self.logger.info("=" * 60)
        
        # Inicializar componentes
        self.camera = None
        #self.motion_detector = None
        self.telegram_alert = None
        self.twilio_alert = None
        self.video_writer = None
        #self.person_detector = None
        self.person_detector = PersonDetector(
            
            confidence_threshold=0.35,      # un poco más permisivo para webcam/poca luz
            min_area=1500,                  # permite personas más pequeñas (lejos)
            min_persistence_frames=3,       # confirma más rápido
            cooldown_seconds=30
        )

        # Control de alertas
        self.last_alert_time = 0
        #self.motion_detected_frames = 0
        
        self._initialize_components()
    
    def _initialize_components(self):
        """Inicializa todos los componentes de la aplicación."""
        # Inicializar cámara
        self.camera = CameraManager(**CAMERA_CONFIG)
        if not self.camera.init_camera():
            self.logger.error("No se pudo inicializar la cámara")
            sys.exit(1)
        
        # Inicializar detector de movimiento
        #self.motion_detector = MotionDetector(**MOTION_CONFIG)
            self.person_detector = PersonDetector(
            confidence_threshold=0.30,
            min_area=1200,
            min_persistence_frames=2,
            cooldown_seconds=20
        )

        # Inicializar Telegram (opcional)
        if TELEGRAM_CONFIG['enabled']:
            self.telegram_alert = TelegramAlert(
                TELEGRAM_CONFIG['bot_token'],
                TELEGRAM_CONFIG['chat_id']
            )
            self.logger.info("Alertas por Telegram habilitadas")
        
        # Twilio removed: SMS alerts disabled by default to avoid costs
        
        # Inicializar grabación de video (opcional)
        if RECORDING_CONFIG['enabled']:
            self._initialize_video_writer()
    
    def _initialize_video_writer(self):
        """Inicializa el grabador de video."""
        try:
            # Obtener un frame para conocer las dimensiones
            success, frame = self.camera.get_frame()
            if success:
                height, width = frame.shape[:2]
                
                # Definir codec y crear VideoWriter
                codec = cv2.VideoWriter_fourcc(*RECORDING_CONFIG['codec'])
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_path = Path(RECORDING_CONFIG['output_dir']) / f"surveillance_{timestamp}.mp4"
                
                self.video_writer = cv2.VideoWriter(
                    str(output_path),
                    codec,
                    RECORDING_CONFIG['fps'],
                    (width, height)
                )
                
                self.logger.info(f"Grabación de video iniciada: {output_path}")
        except Exception as e:
            self.logger.error(f"Error al inicializar grabación: {e}")
    
    def _send_alert(self, message: str, frame=None):
        """Envía alertas (Telegram con foto + texto)."""
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

        # Enviar por Telegram con foto+texto
        if TELEGRAM_CONFIG.get("enabled") and self.telegram_alert:
            self.telegram_alert.send_alert_async(message, str(photo_path) if photo_path else None)
    
    def run(self):
        """Ejecuta el bucle principal de la aplicación."""
        try:
            self.logger.info("Iniciando captura de video...")
            frame_count = 0
            
            while True:
                # Capturar frame
                success, frame = self.camera.get_frame()
                if not success:
                    self.logger.error("Error al capturar frame")
                    break
                
                frame_count += 1
                
                 # Detectar movimiento
                person_detected, annotated_frame = self.person_detector.detect(frame)

                if person_detected:
                    message = (
                        f"🚨 PERSONA DETECTADA\n"
                        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    self._send_alert(message, frame)
                
                # Grabar video si está habilitado
                if self.video_writer and RECORDING_CONFIG['enabled']:
                    self.video_writer.write(annotated_frame)
                
                # Mostrar información en el frame
              
               #info_text = f"Frames: {frame_count} | Confianza: {confidence:.1f}%"
               # cv2.putText(annotated_frame, info_text, (10, 30),
               #            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
                # Mostrar información en el frame
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


                # Mostrar frame
                cv2.imshow("Videovigilancia - Detección de Movimiento", annotated_frame)
                
                # Presionar 'q' para salir
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.logger.info("Usuario ha solicitado salida")
                    break
        
        except KeyboardInterrupt:
            self.logger.info("Interrupción por teclado (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"Error en bucle principal: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Libera todos los recursos."""
        self.logger.info("Limpiando recursos...")
        
        # Liberar cámara
        if self.camera:
            self.camera.release()
        
        # Liberar grabador de video
        if self.video_writer:
            self.video_writer.release()
        
        # Cerrar ventanas de OpenCV
        cv2.destroyAllWindows()
        
        self.logger.info("Recursos liberados correctamente")
        self.logger.info("=" * 60)
        self.logger.info("Aplicación finalizada")
        self.logger.info("=" * 60)


def main():
    """Función principal."""
    app = VideoSurveillanceApp()
    app.run()


if __name__ == "__main__":
    main()