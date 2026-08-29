from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..agents import audit, booking_agent, guardrail, scheduler_agent

router = APIRouter(prefix="/api/jobs", tags=["scheduled-jobs"])


@router.post("", response_model=schemas.ScheduledJobOut)
def create_scheduled_job(payload: schemas.ScheduledJobIn, db: Session = Depends(get_db)):
    """FR-5: attach a ScheduledJob to a journey request / chosen train option."""
    jr = db.get(models.JourneyRequest, payload.journey_request_id)
    if jr is None:
        raise HTTPException(404, "journey request not found")
    option = db.get(models.TrainOption, payload.train_option_id)
    if option is None:
        raise HTTPException(404, "train option not found")

    trigger_time = payload.window_open_time_ist - timedelta(seconds=payload.lead_time_seconds)
    if trigger_time <= datetime.now():
        raise HTTPException(
            400,
            f"window_open_time_ist minus lead_time_seconds ({trigger_time.isoformat()}) is already "
            "in the past. Pick a later window, or reduce lead_time_seconds.",
        )

    job = models.ScheduledJob(
        journey_request_id=payload.journey_request_id,
        train_option_id=payload.train_option_id,
        target_platform=payload.target_platform,
        window_open_time_ist=payload.window_open_time_ist,
        lead_time_seconds=payload.lead_time_seconds,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    scheduler_agent.register_job(job.id)
    return job


@router.get("", response_model=list[schemas.ScheduledJobOut])
def list_scheduled_jobs(db: Session = Depends(get_db)):
    return db.query(models.ScheduledJob).order_by(models.ScheduledJob.created_at.desc()).all()


@router.get("/{job_id}", response_model=schemas.ScheduledJobOut)
def get_scheduled_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.post("/{job_id}/request-token", response_model=schemas.ConfirmationTokenOut)
def request_confirmation_token(job_id: str, db: Session = Depends(get_db)):
    """
    Called when the user opens the confirmation screen for a staged job.
    Issues a short-lived, single-use token - the only credential accepted by
    POST /{job_id}/confirm (FR-7).
    """
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    try:
        token = booking_agent.issue_confirmation_token(db, job)
    except guardrail.GuardrailRejection as exc:
        raise HTTPException(409, str(exc))
    return token


@router.post("/{job_id}/confirm", response_model=schemas.ScheduledJobOut)
def confirm_booking(job_id: str, payload: schemas.CompleteBookingIn, db: Session = Depends(get_db)):
    """
    The human-confirmation gate (FR-7). This is the ONLY endpoint that can
    move a job to 'confirmed', and only with a valid token from
    request-token above - the user must have solved the CAPTCHA and clicked
    confirm in an active session to have gotten here.
    """
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    try:
        job = booking_agent.complete_booking(db, job, payload.token_id)
    except guardrail.GuardrailRejection as exc:
        raise HTTPException(409, str(exc))
    return job
