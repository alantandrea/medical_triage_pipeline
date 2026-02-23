"""
Tests for notification/reporting service.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.reporting.service import NotificationService


class TestNotificationService:
    """Tests for NotificationService."""
    
    def test_service_initialization_defaults(self):
        """Test service initializes with default settings."""
        service = NotificationService()
        assert service.smtp_host == "smtp.gmail.com"
        assert service.smtp_port == 587
    
    def test_service_initialization_custom(self):
        """Test service with custom settings."""
        service = NotificationService(
            smtp_host="custom.smtp.com",
            smtp_port=465,
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        assert service.smtp_host == "custom.smtp.com"
        assert service.smtp_port == 465
        assert service.smtp_user == "user@test.com"
    
    @pytest.mark.asyncio
    async def test_health_check_configured(self):
        """Test health check when SMTP is configured."""
        service = NotificationService(
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        result = await service.health_check()
        assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_not_configured(self):
        """Test health check when SMTP is not configured."""
        service = NotificationService(
            smtp_user="",
            smtp_password="",
            from_email=""
        )
        result = await service.health_check()
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_email_skipped_no_credentials(self):
        """Test email sending skipped when no credentials."""
        service = NotificationService(
            smtp_user="",
            smtp_password=""
        )
        result = await service._send_email(
            "test@example.com",
            "Test Subject",
            "<p>Test body</p>"
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_urgent_alert_structure(self):
        """Test urgent alert email structure."""
        service = NotificationService(
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        
        with patch.object(service, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            
            result = await service.send_urgent_alert(
                recipient="doctor@hospital.com",
                report_id="RPT-001",
                patient_id=12345,
                score=85,
                summary="Critical findings detected",
                findings=[{"finding_notation": "Elevated glucose"}],
                recommendations=["Immediate review needed"]
            )
            
            assert result is True
            mock_send.assert_called_once()
            
            # Check subject contains URGENT
            call_args = mock_send.call_args
            assert "URGENT" in call_args[0][1]
            assert "85" in call_args[0][1]
    
    @pytest.mark.asyncio
    async def test_send_important_notification_structure(self):
        """Test important notification email structure."""
        service = NotificationService(
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        
        with patch.object(service, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            
            result = await service.send_important_notification(
                recipient="doctor@hospital.com",
                report_id="RPT-002",
                patient_id=12345,
                score=60,
                summary="Abnormal values detected"
            )
            
            assert result is True
            mock_send.assert_called_once()
            
            call_args = mock_send.call_args
            assert "Important" in call_args[0][1]
    
    @pytest.mark.asyncio
    async def test_send_daily_digest(self):
        """Test daily digest email."""
        service = NotificationService(
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        
        reports = [
            {"report_id": "RPT-001", "patient_id": 1, "priority_level": "urgent", "score": 85},
            {"report_id": "RPT-002", "patient_id": 2, "priority_level": "important", "score": 60},
            {"report_id": "RPT-003", "patient_id": 3, "priority_level": "routine", "score": 20},
        ]
        
        with patch.object(service, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            
            result = await service.send_daily_digest(
                recipient="admin@hospital.com",
                reports=reports
            )
            
            assert result is True
            mock_send.assert_called_once()
            
            call_args = mock_send.call_args
            assert "Daily" in call_args[0][1]
            assert "3" in call_args[0][1]  # 3 reports
    
    @pytest.mark.asyncio
    async def test_send_error_alert(self):
        """Test error alert email."""
        service = NotificationService(
            smtp_user="user@test.com",
            smtp_password="secret",
            from_email="noreply@test.com"
        )
        
        with patch.object(service, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            
            result = await service.send_error_alert(
                recipient="tech-support@example.com",
                error_type="ModelTimeout",
                error_message="MedGemma 27B timed out",
                context={"report_id": "RPT-001", "tenant_id": "test"}
            )
            
            assert result is True
            mock_send.assert_called_once()
            
            call_args = mock_send.call_args
            assert "Error" in call_args[0][1]
            assert "ModelTimeout" in call_args[0][1]
