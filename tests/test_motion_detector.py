"""
Tests para el módulo de detección de movimiento
"""

import pytest
import numpy as np
import cv2
from src.motion.motion_detector import MotionDetector


class TestMotionDetector:
    """Suite de tests para MotionDetector."""
    
    @pytest.fixture
    def detector(self):
        """Fixture que proporciona una instancia de MotionDetector."""
        return MotionDetector(
            threshold=5.0,
            blur_kernel_size=21,
            min_contour_area=500.0
        )
    
    @pytest.fixture
    def sample_frame(self):
        """Fixture que proporciona un frame de prueba."""
        return np.zeros((480, 640, 3), dtype=np.uint8)
    
    def test_detector_initialization(self, detector):
        """Verifica que el detector se inicializa correctamente."""
        assert detector is not None
        assert detector.threshold == 5.0
        assert detector.blur_kernel_size == 21
        assert detector.min_contour_area == 500.0
    
    def test_detect_motion_with_static_frame(self, detector, sample_frame):
        """Verifica que no se detecte movimiento en frames estáticos."""
        motion_detected, confidence, frame = detector.detect_motion(sample_frame)
        assert motion_detected == False
        assert confidence >= 0.0
    
    def test_detect_motion_with_changed_frame(self, detector, sample_frame):
        """Verifica la detección de movimiento con cambios en el frame."""
        # Primer frame
        motion1, conf1, _ = detector.detect_motion(sample_frame)
        assert motion1 == False
        
        # Frame con cambios
        changed_frame = sample_frame.copy()
        cv2.circle(changed_frame, (320, 240), 50, (255, 255, 255), -1)
        motion2, conf2, _ = detector.detect_motion(changed_frame)
        # Podría detectarse movimiento dependiendo del área
        assert conf2 > conf1
    
    def test_set_threshold(self, detector):
        """Verifica que se pueda cambiar el umbral."""
        original_threshold = detector.threshold
        detector.set_threshold(10.0)
        assert detector.threshold == 10.0
        
        # Valor inválido no debería cambiar
        detector.set_threshold(-1.0)
        assert detector.threshold == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
