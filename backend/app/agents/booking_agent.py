"""
FRD FR-6/FR-7: Booking-Assist Agent.

STAGING (FR-6) is implemented as a stub: real platform login + form-fill
needs actual account credentials and a verified, ToS-compliant automation
path per platform, which this build environment cannot verify. The staging
step here simulates the latency and produces the same state transitions a
real implementation would, so the scheduler/confirmation-gate/notification
flow around it is fully real and testable.

THE GATE ITSELF (FR-7) IS REAL, NOT A STUB:
  - This agent NEVER marks a job 'confirmed' on its own.
  - complete_booking() only runs after guardrail.validate_and_consume_confirmation_token()
    has succeeded for a token tied to this exact job.
  - It also independently re-checks the job is in 'staged_and_waiting' state,
    so a stray call can't skip straight to 'confirmed'.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import config, models
from . import audit, guardrail, notification_agent


async def stage_job(db: Session, job: models.ScheduledJob) -> models.ScheduledJob:
    guardrail.check_rate_limit(db, job.target_platform)

    job.status = "staging"
    db.add(job)
    db.commit()
    audit.log(
        db, agent="booking_assist", action="staging_started", outcome="success",
        target=job.target_platform, scheduled_job_id=job.id, journey_request_id=job.journey_request_id,
    )

    # STUB: real login + form pre-fill would happen here.
    await asyncio.sleep(0.5)

    job.status = "staged_and_waiting"
    db.add(job)
    db.commit()
    db.refresh(job)

    audit.log(
        db, agent="booking_assist", action="staged_and_waiting", outcome="success",
        target=job.target_platform, scheduled_job_id=job.id, journey_request_id=job.journey_request_id,
        details={"note": "Awaiting human confirmation + CAPTCHA per FR-7. Not submitted."},
    )
    return job


def issue_confirmation_token(db: Session, job: models.ScheduledJob) -> models.ConfirmationToken:
    if job.status != "staged_and_waiting":
        raise guardrail.GuardrailRejection(
            f"Cannot issue a confirmation token for job in status '{job.status}'."
        )
    token = models.ConfirmationToken(
        id=uuid.uuid4().hex,
        scheduled_job_id=job.id,
        expires_at=datetime.utcnow() + timedelta(seconds=config.CONFIRMATION_TOKEN_TTL_SECONDS),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    audit.log(
        db, agent="booking_assist", action="confirmation_token_issued", outcome="success",
        target=job.id, scheduled_job_id=job.id,
        details={"expires_at": token.expires_at.isoformat()},
    )
    return token


def complete_booking(db: Session, job: models.ScheduledJob, token_id: str) -> models.ScheduledJob:
    """
    The only path from 'staged_and_waiting' to 'confirmed'. Requires a human
    to have already solved the CAPTCHA and clicked confirm in the UI - this
    function is what that click calls, via the /confirm route.
    """
    if job.status != "staged_and_waiting":
        audit.log(
            db, agent="booking_assist", action="complete_booking", outcome="rejected",
            target=job.id, scheduled_job_id=job.id,
            details={"reason": f"job not in staged_and_waiting (was {job.status})"},
        )
        raise guardrail.GuardrailRejection(f"Job is not awaiting confirmation (status: {job.status}).")

    # Independent guardrail check - raises on any failure, nothing below runs.
    guardrail.validate_and_consume_confirmation_token(db, token_id, job.id)

    # STUB: this is where the actual final "Pay/Confirm" click on the
    # platform's page would be triggered, using the CAPTCHA the human
    # already solved in the browser session. No auto-CAPTCHA-solving,
    # ever, per PRD S2 / FRD FR-7.
    job.status = "confirmed"
    db.add(job)
    db.commit()
    db.refresh(job)

    audit.log(
        db, agent="booking_assist", action="complete_booking", outcome="success",
        target=job.target_platform, scheduled_job_id=job.id, journey_request_id=job.journey_request_id,
        details={"confirmation_token_id": token_id},
    )

    notification_agent.send(
        db,
        f"Payment status: CONFIRMED for job {job.id} on {job.target_platform}. "
        f"(This build's booking flow is a stub - see docs/FRD.md FR-6 - so this reflects "
        f"the mock job status, not a real platform transaction.)",
        level="info",
        scheduled_job_id=job.id,
    )
    return job
