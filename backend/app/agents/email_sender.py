"""
FR-8 email channel. Sends status notifications (staging ready, booking
confirmed/failed) to the user's own inbox via their own SMTP account.

This intentionally never touches IRCTC/platform credentials - it's a
separate, ordinary email send using an app password for the user's own
mail account (e.g. a Gmail "app password", not their real Gmail password).
If SMTP isn't configured, this silently no-ops so the rest of the app keeps
working with in-app notifications only.
"""
import logging
import smtplib
from email.mime.text import MIMEText

from .. import config

logger = logging.getLogger("ticket_agent.email")


def is_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD and config.NOTIFY_EMAIL_TO)


def send_email(subject: str, body: str) -> bool:
    if not is_configured():
        logger.info("SMTP not configured - skipping email send (subject=%r)", subject)
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = config.NOTIFY_EMAIL_TO

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_FROM, [config.NOTIFY_EMAIL_TO], msg.as_string())
        return True
    except Exception:
        logger.exception("Failed to send notification email (subject=%r)", subject)
        return False
