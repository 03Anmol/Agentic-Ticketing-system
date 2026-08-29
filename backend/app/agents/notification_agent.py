"""
FR-8. Channel is pluggable and currently a DB-backed "inbox" the frontend
polls (see models.Notification docstring) - swap send() to also call a real
push/SMS/email provider once one is chosen (PRD S13 open question).
"""
import logging

from sqlalchemy.orm import Session

from .. import models
from . import email_sender

logger = logging.getLogger("ticket_agent.notify")

_LEVEL_SUBJECTS = {
    "action_required": "[Ticket Agent] Action needed",
    "error": "[Ticket Agent] Something failed",
    "info": "[Ticket Agent] Status update",
}


def send(db: Session, message: str, *, level: str = "info", scheduled_job_id: str | None = None) -> models.Notification:
    note = models.Notification(message=message, level=level, scheduled_job_id=scheduled_job_id)
    db.add(note)
    db.commit()
    db.refresh(note)
    logger.info("[notify:%s] %s", level, message)

    email_sender.send_email(_LEVEL_SUBJECTS.get(level, _LEVEL_SUBJECTS["info"]), message)
    return note
