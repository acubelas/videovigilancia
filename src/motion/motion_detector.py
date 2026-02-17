"""
Detector de movimiento en video
"""

import cv2
import numpy as np
import logging
from typing import Tuple, Optional


class MotionDetector:
    """
    Detecta movimiento en fotogramas de video usando diferencias de fotogramas.
    
    Attributes:
        threshold: Umbral de píxeles diferentes para detectar movimiento
        blur_kernel_size: Tamaño del kernel para aplicar desenfoque
        min_contour_area: Área mínima de contorno para considerar como movimiento
    """
    
    def __init__(self, threshold: float = 5.0, blur_kernel_size: int = 21, 
                 min_contour_area: float = 500.0, confidence_threshold: float = 2.0,
                 alert_cooldown_seconds: int = 30):
        """
        Inicializa el detector de movimiento.
        
        Args:
            threshold: Umbral de diferencia de píxeles (0-100)
            blur_kernel_size: Tamaño del kernel gaussiano (debe ser impar)
            min_contour_area: Área mínima de contorno para detectar movimiento
        """
        self.logger = logging.getLogger(__name__)
        self.threshold = threshold
        self.blur_kernel_size = blur_kernel_size
        self.min_contour_area = min_contour_area
        self.confidence_threshold = confidence_threshold
        self.alert_cooldown_seconds = alert_cooldown_seconds
        self.previous_frame = None
        
    def detect_motion(self, frame: object) -> Tuple[bool, Optional[float], object]:
        """
        Detecta movimiento en el fotograma actual comparándolo con el anterior.
        
        Args:
            frame: Fotograma de video (numpy array)
            
        Returns:
            Tupla (motion_detected, confidence, annotated_frame)
            - motion_detected: True si se detectó movimiento
            - confidence: Porcentaje de cambio detectado (0-100)
            - annotated_frame: Fotograma con anotaciones de movimiento
        """
        try:
            # Convertir a escala de grises
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Aplicar desenfoque gaussiano
            gray = cv2.GaussianBlur(gray, (self.blur_kernel_size, self.blur_kernel_size), 0)
            
            # Si es el primer fotograma, guardarlo y retornar sin movimiento
            if self.previous_frame is None:
                self.previous_frame = gray
                return False, 0.0, frame
            
            # Calcular diferencia entre fotogramas
            frame_diff = cv2.absdiff(self.previous_frame, gray)
            
            # Aplicar umbral
            _, thresh = cv2.threshold(frame_diff, 30, 255, cv2.THRESH_BINARY)
            
            # Aplicar dilatación y erosión
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            
            # Encontrar contornos
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Contar píxeles diferentes
            changed_pixels = np.sum(thresh / 255)
            total_pixels = thresh.shape[0] * thresh.shape[1]
            confidence = (changed_pixels / total_pixels) * 100
            
            # Detectar movimiento basado en contornos
            motion_detected = False
            annotated_frame = frame.copy()
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > self.min_contour_area:
                    motion_detected = True
                    # Dibujar rectángulo alrededor del movimiento
                    x, y, w, h = cv2.boundingRect(contour)
                    cv2.rectangle(annotated_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(annotated_frame, f"Motion: {confidence:.1f}%", (x, y - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Actualizar frame anterior
            self.previous_frame = gray
            
            return motion_detected, confidence, annotated_frame
            
        except Exception as e:
            self.logger.error(f"Error en detección de movimiento: {e}")
            return False, 0.0, frame
    
    def set_threshold(self, threshold: float):
        """Establece el umbral de detección."""
        if 0 <= threshold <= 100:
            self.threshold = threshold
        else:
            self.logger.warning(f"Umbral inválido: {threshold}")
