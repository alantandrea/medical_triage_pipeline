"""
Email notification service for clinical alerts.
"""
import html
import logging
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from ..config import settings
from .tapestry import generate_tapestry

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Email notification service for clinical alerts.
    
    Supports:
    - Urgent alerts (immediate)
    - Important notifications
    - Daily digest compilation
    """
    
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None
    ):
        self.smtp_host = smtp_host or settings.smtp_host
        self.smtp_port = smtp_port or settings.smtp_port
        self.smtp_user = smtp_user or settings.smtp_user
        self.smtp_password = smtp_password or settings.smtp_password
        self.from_email = from_email or settings.from_email
    
    async def send_urgent_alert(
        self,
        recipient: str,
        report_id: str,
        patient_id: int,
        score: int,
        summary: str,
        findings: List[dict],
        recommendations: List[str],
        patient_history: Optional[list] = None,
        mongodb_client=None,
        tenant_id: Optional[str] = None,
        medgemma_27b=None,
    ) -> bool:
        """
        Send urgent alert email for critical findings.
        
        Args:
            recipient: Email address
            report_id: Report identifier
            patient_id: Patient ID (no PHI in email!)
            score: Urgency score
            summary: AI analysis summary
            findings: List of findings
            recommendations: List of recommendations
        
        Returns:
            True if sent successfully
        """
        subject = f"🚨 URGENT: Medical Report Requires Immediate Review (Score: {score})"
        
        # Build HTML body
        findings_html = "\n".join([
            f"<li>{html.escape(f.get('finding_notation', 'Unknown finding'))}</li>"
            for f in findings
        ])
        
        recommendations_html = "\n".join([
            f"<li>{html.escape(r)}</li>" for r in recommendations
        ])
        
        # Generate tapestry if enabled
        tapestry_html = ""
        if settings.tapestry_enabled and mongodb_client and tenant_id:
            try:
                tapestry_html = await generate_tapestry(mongodb_client, tenant_id, patient_id, medgemma_27b=medgemma_27b)
            except Exception as e:
                logger.warning(f"Tapestry generation failed, sending email without it: {e}")
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background-color: #ff4444; color: white; padding: 15px; border-radius: 5px;">
                <h2>⚠️ URGENT: Immediate Clinical Review Required</h2>
            </div>
            
            <div style="padding: 20px;">
                <p><strong>Report ID:</strong> {html.escape(str(report_id))}</p>
                <p><strong>Patient ID:</strong> {html.escape(str(patient_id))}</p>
                <p><strong>Urgency Score:</strong> {score}/100</p>
                
                <h3>Summary</h3>
                <p>{html.escape(summary)}</p>
                
                <h3>Key Findings</h3>
                <ul>{findings_html}</ul>
                
                <h3>Recommended Actions</h3>
                <ul>{recommendations_html}</ul>
                
                {self._build_patient_history_html(patient_history or [])}
                
                {tapestry_html}
                
                <hr>
                <p style="color: #666; font-size: 12px;">
                    This is an automated alert from the MedGemma Triage System.
                    Please review the full report in your clinical system.
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self._send_email(recipient, subject, html_body)

    async def send_important_notification(
        self,
        recipient: str,
        report_id: str,
        patient_id: int,
        score: int,
        summary: str,
        patient_history: Optional[list] = None,
        mongodb_client=None,
        tenant_id: Optional[str] = None,
        medgemma_27b=None,
    ) -> bool:
        """
        Send notification for important (non-urgent) findings.
        """
        subject = f"📋 Important: Medical Report Review Needed (Score: {score})"
        
        # Generate tapestry if enabled
        tapestry_html = ""
        if settings.tapestry_enabled and mongodb_client and tenant_id:
            try:
                tapestry_html = await generate_tapestry(mongodb_client, tenant_id, patient_id, medgemma_27b=medgemma_27b)
            except Exception as e:
                logger.warning(f"Tapestry generation failed, sending email without it: {e}")
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background-color: #ff9800; color: white; padding: 15px; border-radius: 5px;">
                <h2>📋 Important: Clinical Review Recommended</h2>
            </div>
            
            <div style="padding: 20px;">
                <p><strong>Report ID:</strong> {html.escape(str(report_id))}</p>
                <p><strong>Patient ID:</strong> {html.escape(str(patient_id))}</p>
                <p><strong>Priority Score:</strong> {score}/100</p>
                
                <h3>Summary</h3>
                <p>{html.escape(summary)}</p>
                
                {self._build_patient_history_html(patient_history or [])}
                
                {tapestry_html}
                
                <hr>
                <p style="color: #666; font-size: 12px;">
                    This is an automated notification from the MedGemma Triage System.
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self._send_email(recipient, subject, html_body)
    
    async def send_daily_digest(
        self,
        recipient: str,
        reports: List[dict]
    ) -> bool:
        """
        Send daily digest of processed reports.
        
        Args:
            recipient: Email address
            reports: List of report summaries
        """
        subject = f"📊 Daily Report Digest: {len(reports)} Reports Processed"
        
        # Group by priority
        urgent = [r for r in reports if r.get("priority_level") == "urgent"]
        important = [r for r in reports if r.get("priority_level") == "important"]
        followup = [r for r in reports if r.get("priority_level") == "followup"]
        routine = [r for r in reports if r.get("priority_level") == "routine"]
        
        def format_report_list(reports_list: List[dict]) -> str:
            if not reports_list:
                return "<li>None</li>"
            return "\n".join([
                f"<li>Report {html.escape(str(r.get('report_id')))} - Patient {html.escape(str(r.get('patient_id')))} (Score: {r.get('score', 0)})</li>"
                for r in reports_list
            ])
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background-color: #2196F3; color: white; padding: 15px; border-radius: 5px;">
                <h2>📊 Daily Report Digest</h2>
            </div>
            
            <div style="padding: 20px;">
                <h3>Summary</h3>
                <ul>
                    <li>🚨 Urgent: {len(urgent)}</li>
                    <li>📋 Important: {len(important)}</li>
                    <li>📝 Follow-up: {len(followup)}</li>
                    <li>✅ Routine: {len(routine)}</li>
                </ul>
                
                <h3>🚨 Urgent Reports</h3>
                <ul>{format_report_list(urgent)}</ul>
                
                <h3>📋 Important Reports</h3>
                <ul>{format_report_list(important)}</ul>
                
                <h3>📝 Follow-up Reports</h3>
                <ul>{format_report_list(followup)}</ul>
                
                <hr>
                <p style="color: #666; font-size: 12px;">
                    MedGemma Triage System - Daily Digest
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self._send_email(recipient, subject, html_body)

    async def send_error_alert(
        self,
        recipient: str,
        error_type: str,
        error_message: str,
        context: dict
    ) -> bool:
        """
        Send error alert to tech support.
        """
        subject = f"⚠️ MedGemma System Error: {error_type}"
        
        context_html = "\n".join([
            f"<li><strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}</li>"
            for k, v in context.items()
        ])
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background-color: #f44336; color: white; padding: 15px; border-radius: 5px;">
                <h2>⚠️ System Error Alert</h2>
            </div>
            
            <div style="padding: 20px;">
                <p><strong>Error Type:</strong> {html.escape(error_type)}</p>
                <p><strong>Message:</strong> {html.escape(error_message)}</p>
                
                <h3>Context</h3>
                <ul>{context_html}</ul>
                
                <hr>
                <p style="color: #666; font-size: 12px;">
                    MedGemma Triage System - Error Alert
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self._send_email(recipient, subject, html_body)
    
    async def _send_email(
        self,
        recipient: str,
        subject: str,
        html_body: str
    ) -> bool:
        """
        Send email via SMTP.
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email")
            return False
        
        try:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.from_email
            message["To"] = recipient
            
            # Attach HTML body
            html_part = MIMEText(html_body, "html")
            message.attach(html_part)
            
            # Send via SMTP
            # Port 465 = implicit TLS (use_tls=True)
            # Port 587 = STARTTLS (start_tls=True)
            use_implicit_tls = self.smtp_port == 465
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=not use_implicit_tls,
                use_tls=use_implicit_tls,
                timeout=15
            )
            
            logger.info(f"Email sent to {recipient}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {recipient}: {e}")
            return False
    
    def _build_patient_history_html(self, history: list) -> str:
        """Build an HTML table of patient history for email notifications."""
        if not history:
            return ""

        rows = ""
        for item in history:
            item_type = "📋 Report" if item["type"] == "report" else "💬 Note"
            score = item.get("score", 0)
            if score >= 70:
                color = "#ff4444"
            elif score >= 50:
                color = "#ff9800"
            elif score >= 30:
                color = "#2196F3"
            else:
                color = "#4CAF50"

            date_str = item.get("date", "")
            if date_str and len(date_str) > 19:
                date_str = date_str[:19].replace("T", " ")

            summary = html.escape(item.get("summary", "")[:200])
            rows += f"""
            <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{html.escape(date_str)}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{item_type}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;color:{color};font-weight:bold;">{score}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{summary}</td>
            </tr>"""

        return f"""
        <div style="margin-top:30px;padding-top:20px;border-top:2px solid #ddd;">
            <h3 style="color:#555;">📂 Patient History</h3>
            <p style="color:#888;font-size:12px;">Recent reports and notes on file for this patient.</p>
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <thead>
                    <tr style="background-color:#f5f5f5;">
                        <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #ddd;">Date</th>
                        <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #ddd;">Type</th>
                        <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #ddd;">Score</th>
                        <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #ddd;">Summary</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>
        </div>"""

    async def health_check(self) -> bool:
        """Check if SMTP is configured."""
        return bool(self.smtp_user and self.smtp_password and self.from_email)
