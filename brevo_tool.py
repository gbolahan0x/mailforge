import requests
import logging

log = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

class BrevoClient:
    """Send emails via Brevo Transactional Email API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": self.api_key,
        }

    def send(self, from_addr: str, from_name: str, to_addrs: list[str],
             subject: str, body: str, html: str = None) -> bool:
        """
        Send an email via Brevo. Supports plain text and optional HTML body.
        Returns True on success.
        """
        payload = {
            "sender": {"name": from_name, "email": from_addr},
            "to": [{"email": addr} for addr in to_addrs],
            "subject": subject,
            "textContent": body,
        }

        if html:
            payload["htmlContent"] = html

        try:
            response = requests.post(BREVO_API_URL, json=payload, headers=self.headers)
            response.raise_for_status()
            log.info(f"✅ Email sent via Brevo to {to_addrs}")
            return True
        except requests.exceptions.HTTPError as e:
            log.error(f"❌ Brevo HTTP error: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            log.error(f"❌ Send failed: {e}")
            return False
