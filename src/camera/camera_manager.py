"""
Gestor de captura de video desde cámaras web
"""

import cv2
import logging
from typing import Optional, Tuple


class CameraManager:
    """
    Gestiona la captura de video desde una cámara web.
    
    Attributes:
        camera_index: Índice de la cámara (0 para la cámara predeterminada)
        frame_width: Ancho del fotograma
        frame_height: Alto del fotograma
        fps: Fotogramas por segundo
    """
    
    def __init__(self, camera_index: int = 0, frame_width: int = 640, 
                 frame_height: int = 480, fps: int = 30):
        """
        Inicializa el gestor de cámara.
        
        Args:
            camera_index: Índice de la cámara a usar
            frame_width: Ancho del fotograma capturado
            frame_height: Alto del fotograma capturado
            fps: Fotogramas por segundo
        """
        self.logger = logging.getLogger(__name__)
        self.camera_index = camera_index
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.fps = fps
        self.cap = None
        
    def init_camera(self) -> bool:
        """
        Inicializa la cámara.
        
        Returns:
            True si la inicialización fue exitosa, False en caso contrario
        """
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            
            if not self.cap.isOpened():
                self.logger.error(f"No se pudo abrir la cámara con índice {self.camera_index}")
                return False
            
            # Configurar propiedades de la cámara
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            
            self.logger.info(f"Cámara inicializada correctamente: {self.frame_width}x{self.frame_height} @ {self.fps} FPS")
            return True
            
        except Exception as e:
            self.logger.error(f"Error al inicializar la cámara: {e}")
            return False
    
    def get_frame(self) -> Tuple[bool, Optional[object]]:
        """
        Obtiene el siguiente fotograma de la cámara.
        
        Returns:
            Tupla (success, frame) donde success indica si la captura fue exitosa
        """
        if self.cap is None:
            self.logger.warning("La cámara no está inicializada")
            return False, None
        
        try:
            success, frame = self.cap.read()
            return success, frame
        except Exception as e:
            self.logger.error(f"Error al capturar fotograma: {e}")
            return False, None
    
    def release(self):
        """Libera los recursos de la cámara."""
        if self.cap is not None:
            self.cap.release()
            self.logger.info("Cámara liberada")
    
    def __enter__(self):
        """Context manager: entrada."""
        self.init_camera()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager: salida."""
        self.release()
