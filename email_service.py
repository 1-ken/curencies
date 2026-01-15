"""
Email notification service using SendGrid.
"""
import logging
import os
import certifi
from typing import Dict, Any
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import ssl

logger = logging.getLogger(__name__)

# Configure SSL certificate verification
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())


class EmailService:
    """Handles sending alert emails via SendGrid."""

    def __init__(self, api_key: str):
        self.sg = SendGridAPIClient(api_key)
        self.from_email = os.getenv("FROM_EMAIL", "noreply@financeobserver.app")

    def send_price_alert(
        self,
        to_email: str,
        pair: str,
        target_price: float,
        current_price: float,
        condition: str,
        custom_message: str = "",
    ) -> bool:
        """Send price alert email."""
        try:
            # Build custom message section if provided
            custom_msg_html = ""
            if custom_message:
                custom_msg_html = f"""
                        <div style="background-color: #f0f8ff; border-left: 4px solid #007bff; padding: 12px; margin: 15px 0;">
                            <strong>Your Message:</strong><br>
                            <p style="margin: 8px 0; white-space: pre-wrap;">{custom_message}</p>
                        </div>
                """
            
            message = Mail(
                from_email=self.from_email,
                to_emails=to_email,
                subject=f"🚨 Price Alert: {pair} reached {condition} {target_price}",
                html_content=f"""
                <html>
                    <body>
                        <h2>Price Alert Triggered!</h2>
                        <p>Your alert for <strong>{pair}</strong> has been triggered.</p>
                        <ul>
                            <li><strong>Pair:</strong> {pair}</li>
                            <li><strong>Condition:</strong> Price {condition} {target_price}</li>
                            <li><strong>Current Price:</strong> {current_price}</li>
                            <li><strong>Time:</strong> {self._get_timestamp()}</li>
                        </ul>
                        {custom_msg_html}
                        <p><a href="http://localhost:8000">View Dashboard</a></p>
                    </body>
                </html>
                """,
            )
            response = self.sg.send(message)
            logger.info(f"Email sent to {to_email} (status: {response.status_code})")
            return response.status_code == 202
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    def _get_timestamp() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
