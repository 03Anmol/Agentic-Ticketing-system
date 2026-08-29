"""FRD FR-10: append-only audit log. Every agent action goes through here."""
from sqlalchemy.orm import Session

from .. import models


def log(
    db: Session,
    *,
    agent: str,
    action: str,
    outcome: str,
    target: str | None = None,
    details: dict | None = None,
    journey_request_id: str | None = None,
    scheduled_job_id: str | None = None,
) -> models.AuditLogEntry:
    entry = models.AuditLogEntry(
        agent=agent,
        action=action,
        outcome=outcome,
        target=target,
        details=details,
        related_journey_request_id=journey_request_id,
        related_scheduled_job_id=scheduled_job_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
