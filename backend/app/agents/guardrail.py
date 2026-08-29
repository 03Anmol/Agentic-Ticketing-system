"""
FRD FR-9: Guardrail / Policy Agent.

This is the second, independent enforcement point for FR-7's human-confirmation
gate (the first is in booking_agent.py itself). A bug in the booking agent
must not be enough, on its own, to submit a booking unattended - see
docs/PRD.md S2 and docs/FRD.md FR-7/FR-9 for why this exists.

Also owns per-platform rate limiting so search/login traffic doesn't trip a
platform's anti-abuse systems.
"""
import time
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from .. import config, models
from . import audit


class GuardrailRejection(Exception):
    pass


_call_timestamps: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(db: Session, platform: str) -> None:
    now = time.monotonic()
    window_start = now - config.GUARDRAIL_RATE_LIMIT_WINDOW_SECONDS
    calls = [t for t in _call_timestamps[platform] if t >= window_start]
    if len(calls) >= config.GUARDRAIL_RATE_LIMIT_MAX_CALLS:
        audit.log(
            db, agent="guardrail", action="rate_limit_block", outcome="rejected",
            target=platform,
            details={"calls_in_window": len(calls), "limit": config.GUARDRAIL_RATE_LIMIT_MAX_CALLS},
        )
        raise GuardrailRejection(f"Rate limit exceeded for platform {platform}")
    calls.append(now)
    _call_timestamps[platform] = calls


def validate_and_consume_confirmation_token(
    db: Session, token_id: str, scheduled_job_id: str
) -> models.ConfirmationToken:
    """
    The ONLY way a ScheduledJob may move to 'confirmed'. Requires a token that:
      - exists
      - belongs to this scheduled_job_id
      - has not already been used
      - has not expired

    Any failure is logged and raises - callers must not proceed on failure.
    """
    token = db.get(models.ConfirmationToken, token_id)

    if token is None or token.scheduled_job_id != scheduled_job_id:
        audit.log(
            db, agent="guardrail", action="confirmation_token_check", outcome="rejected",
            target=scheduled_job_id, details={"reason": "token_not_found_or_mismatched"},
            scheduled_job_id=scheduled_job_id,
        )
        raise GuardrailRejection("Confirmation token not found or does not match this job.")

    if token.used:
        audit.log(
            db, agent="guardrail", action="confirmation_token_check", outcome="rejected",
            target=scheduled_job_id, details={"reason": "token_already_used"},
            scheduled_job_id=scheduled_job_id,
        )
        raise GuardrailRejection("Confirmation token has already been used.")

    if datetime.utcnow() > token.expires_at:
        audit.log(
            db, agent="guardrail", action="confirmation_token_check", outcome="rejected",
            target=scheduled_job_id, details={"reason": "token_expired"},
            scheduled_job_id=scheduled_job_id,
        )
        raise GuardrailRejection("Confirmation token has expired. Please restage.")

    token.used = True
    db.add(token)
    db.commit()

    audit.log(
        db, agent="guardrail", action="confirmation_token_check", outcome="success",
        target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
    )
    return token
