from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..agents import audit, booking_agent, guardrail, handoff_agent, notification_agent, scheduler_agent

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
    scheduler_agent.register_readiness_reminders(job.id)
    return job


@router.post("/immediate", response_model=schemas.ScheduledJobOut)
def create_immediate_job(payload: schemas.ImmediateJobIn, db: Session = Depends(get_db)):
    """
    Book now - no Tatkal window to wait for.

    Most bookings are this. Only Tatkal has a timed window worth scheduling
    against, so requiring a window_open_time for everything (as POST /api/jobs
    does) forces users to invent one for journeys that have none. This creates
    the job already staged, so the Launch Pad opens immediately, and registers
    no scheduler entry or pre-window reminders - there's nothing to wait for.
    """
    jr = db.get(models.JourneyRequest, payload.journey_request_id)
    if jr is None:
        raise HTTPException(404, "journey request not found")
    option = db.get(models.TrainOption, payload.train_option_id)
    if option is None:
        raise HTTPException(404, "train option not found")

    job = models.ScheduledJob(
        journey_request_id=payload.journey_request_id,
        train_option_id=payload.train_option_id,
        target_platform=payload.target_platform,
        window_open_time_ist=datetime.now(),
        lead_time_seconds=0,
        booking_mode="immediate",
        status="staged_and_waiting",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    audit.log(
        db, agent="handoff", action="immediate_job_created", outcome="success",
        target=job.id, scheduled_job_id=job.id, journey_request_id=jr.id,
        details={"platform": job.target_platform, "train_option_id": option.id},
    )
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


@router.get("/{job_id}/handoff")
def get_handoff(job_id: str, db: Session = Depends(get_db)):
    """
    The Launch Pad payload: countdown, prep checklist, exact selection spec,
    paste-ready passengers, and the link to IRCTC's own booking page.

    Read-only and generates nothing on the platform's side - see
    agents/handoff_agent.py for why this is the furthest automation can go.
    """
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return handoff_agent.build_handoff(db, job)


@router.post("/{job_id}/checklist")
def set_checklist_step(job_id: str, payload: schemas.ChecklistStepIn, db: Session = Depends(get_db)):
    """
    Marks one Launch Pad step done or not-done, and returns the refreshed
    handoff so the UI advances to the next step in a single round trip.
    """
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")

    valid_keys = {s["key"] for s in handoff_agent.build_handoff(db, job)["checklist"]}
    if payload.step_key not in valid_keys:
        raise HTTPException(400, f"unknown step '{payload.step_key}' for this job")

    # Rebind rather than mutate: SQLAlchemy's change detection on a plain JSON
    # column doesn't see in-place dict edits, so mutating would silently fail
    # to persist.
    progress = dict(job.checklist_progress or {})
    if payload.done:
        progress[payload.step_key] = datetime.now().isoformat()
    else:
        progress.pop(payload.step_key, None)
    job.checklist_progress = progress

    db.add(job)
    db.commit()
    db.refresh(job)

    audit.log(
        db, agent="handoff", action="checklist_step_updated", outcome="success",
        target=job.id, scheduled_job_id=job.id,
        details={"step": payload.step_key, "done": payload.done},
    )
    return handoff_agent.build_handoff(db, job)


@router.post("/{job_id}/pnr", response_model=schemas.ScheduledJobOut)
def record_pnr(job_id: str, payload: schemas.RecordPnrIn, db: Session = Depends(get_db)):
    """
    Closes the loop after the user books on IRCTC themselves: stores the PNR,
    audits it, and emails the confirmation.

    Note this deliberately does NOT set status='confirmed'. That status belongs
    to this app's internal mock flow (see booking_agent.complete_booking); a
    real railway booking is recorded by the presence of a PNR, and conflating
    the two would make the audit log lie about which bookings are real.
    """
    job = db.get(models.ScheduledJob, job_id)
    if job is None:
        raise HTTPException(404, "job not found")

    pnr = payload.pnr.strip()
    if not pnr.isdigit() or len(pnr) != 10:
        raise HTTPException(400, "An Indian Railways PNR is exactly 10 digits.")

    job.pnr = pnr
    job.booked_at = datetime.now()
    db.add(job)
    db.commit()
    db.refresh(job)

    audit.log(
        db, agent="handoff", action="pnr_recorded", outcome="success",
        target=job.id, scheduled_job_id=job.id, journey_request_id=job.journey_request_id,
        details={"pnr": pnr, "booked_by": "human_on_platform"},
    )
    notification_agent.send(
        db,
        f"Booking recorded: PNR {pnr} on {job.target_platform}. "
        f"Check status at https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html",
        level="info",
        scheduled_job_id=job.id,
    )
    return job


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
