"""Email via Brevo's HTTP API (Render free blocks SMTP). Without a key, links are printed to the console."""
import logging

import httpx

from app.config import settings

log = logging.getLogger("smartprep.email")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(to_email: str, subject: str, html: str, to_name: str = "") -> bool:
    """Send one email. Meant to run in a BackgroundTask; never raises."""
    if not settings.email_enabled:
        print(f"\n[email disabled] To: {to_email}\nSubject: {subject}\n{html}\n", flush=True)
        return False
    payload = {
        "sender": {"name": settings.MAIL_FROM_NAME, "email": settings.MAIL_FROM},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        r = httpx.post(
            BREVO_URL,
            json=payload,
            headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
            timeout=10,
        )
        if r.status_code >= 300:
            log.warning("Brevo send failed (%s) to %s", r.status_code, to_email)
            return False
        return True
    except httpx.HTTPError as exc:
        log.warning("Brevo send error to %s: %s", to_email, type(exc).__name__)
        return False


def wrap(title: str, body_html: str) -> str:
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto'>"
        f"<h2 style='color:#4338ca'>{settings.APP_NAME}</h2><h3>{title}</h3>{body_html}"
        "<p style='color:#888;font-size:12px'>Romblon State University – Cajidiocan Campus · LET Review</p></div>"
    )


def button(url: str, label: str) -> str:
    return (
        f"<p><a href='{url}' style='background:#4f46e5;color:#fff;padding:10px 18px;border-radius:6px;"
        f"text-decoration:none'>{label}</a></p><p style='font-size:12px'>Or open: {url}</p>"
    )
