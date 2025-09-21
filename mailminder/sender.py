import base64
import datetime
from email.mime.text import MIMEText

from . import config


def _create_message_html(sender: str, to: str, subject: str, html_body: str) -> dict:
    msg = MIMEText(html_body, "html")
    msg["to"], msg["from"], msg["subject"] = to, sender, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def send_digest(service, html_body: str, recipient: str | None = None):
    """Send the daily digest via Gmail API."""
    recipient = recipient or config.SUMMARY_RECIPIENT
    subject = f"Daily Digest – {datetime.date.today():%Y-%m-%d}"
    message = _create_message_html("me", recipient, subject, html_body)
    service.users().messages().send(userId="me", body=message).execute()
