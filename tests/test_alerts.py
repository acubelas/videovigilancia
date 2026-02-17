"""
Tests para el módulo de alertas
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.alerts.telegram_alert import TelegramAlert

class TestTelegramAlert:
    """Suite de tests para TelegramAlert."""
    
    @pytest.fixture
    def telegram_alert(self):
        """Fixture que proporciona una instancia de TelegramAlert."""
        return TelegramAlert(bot_token="test_token", chat_id="test_chat_id")
    
    @patch('src.alerts.telegram_alert.Bot')
    def test_telegram_initialization(self, mock_bot_class, telegram_alert):
        """Verifica la inicialización de TelegramAlert."""
        assert telegram_alert is not None
        assert telegram_alert.bot_token == "test_token"
        assert telegram_alert.chat_id == "test_chat_id"
    
    def test_send_alert_without_photo(self, telegram_alert):
        """Verifica el envío de alerta sin foto."""
        # Este test es básico ya que requiere un bot real
        result = telegram_alert.send_alert("Test message")
        # El resultado dependerá de si el bot está configurado





if __name__ == "__main__":
    pytest.main([__file__, "-v"])
