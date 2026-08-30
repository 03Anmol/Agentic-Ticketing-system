"""
FRD FR-5: Scheduler / Cron Agent.

Backed by APScheduler with a SQLAlchemy job store on the same DB, so
registered jobs survive a process restart (PRD success metric: staged within
5s of window open - that only holds if the scheduler itself is durable).
All trigger times are treated as IST already (the caller/API is responsible
for that - see routers/schedule.py); this module does not do timezone math
of its own beyond what APScheduler needs for its internal bookkeeping.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.events import EVENT_JOB_MISSED, JobExecutionEvent

from .. import config
from ..database import SessionLocal
from .. import models
from . import booking_agent, notification_agent, audit

logger = logging.getLogger("ticket_agent.scheduler")

_scheduler: AsyncIOScheduler | None = None

# Missed-fire grace window (FRD S7): if the process was down at trigger time,
# fire immediately on recovery only within this many seconds; else mark failed.
MISFIRE_GRACE_SECONDS = 30


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=config.DATABASE_URL)},
        )
    return _scheduler


def _on_job_missed(event: JobExecutionEvent) -> None:
    """
    APScheduler skips a job silently once it's more than MISFIRE_GRACE_SECONDS
    past due (e.g. the app was asleep/not running at the trigger moment). Left
    alone, that leaves a ScheduledJob stuck at 'pending' forever with no
    explanation - FRD S7 explicitly requires this to surface as a failure,
    not vanish. This listener is that surfacing.
    """
    scheduled_job_id = event.job_id
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, scheduled_job_id)
        if job is None or job.status != "pending":
            return
        job.status = "failed"
        db.add(job)
        db.commit()
        audit.log(
            db, agent="scheduler", action="job_missed", outcome="error",
            target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
            details={"reason": f"trigger time passed more than {MISFIRE_GRACE_SECONDS}s ago before it ran"},
        )
        notification_agent.send(
            db,
            f"Scheduled job {job.id} on {job.target_platform} MISSED its staging window "
            f"(the app likely wasn't running at the right moment). Reschedule if the window is still open.",
            level="error",
            scheduled_job_id=job.id,
        )
    finally:
        db.close()


def start():
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
        scheduler.start()
        logger.info("Scheduler started")


def shutdown():
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)


def register_job(scheduled_job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, scheduled_job_id)
        if job is None:
            raise ValueError(f"No ScheduledJob with id {scheduled_job_id}")

        trigger_time = job.window_open_time_ist - timedelta(seconds=job.lead_time_seconds)

        get_scheduler().add_job(
            _fire_staging,
            "date",
            run_date=trigger_time,
            args=[scheduled_job_id],
            id=scheduled_job_id,
            replace_existing=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
        audit.log(
            db, agent="scheduler", action="job_registered", outcome="success",
            target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
            details={"trigger_time": trigger_time.isoformat(), "lead_time_seconds": job.lead_time_seconds},
        )
    finally:
        db.close()


# Readiness reminders (see agents/handoff_agent.py). Each is a nudge to do one
# prep step that must happen BEFORE the window, because doing it during the
# window is what loses the seat. Keyed to the same steps handoff_agent's
# checklist renders, so the notification and the UI never disagree.
_REMINDERS = [
    (30 * 60, "Save every passenger to your IRCTC Master List now (My Profile > Master List). "
              "At the window they become one-click selections instead of typed fields."),
    (20 * 60, "Top up your IRCTC eWallet to cover the fare. It settles in ~2s and won't fail "
              "like a bank gateway can mid-Tatkal."),
    (10 * 60, "Log in to IRCTC now and leave the tab open - the login page itself slows down "
              "as the window approaches."),
]


def register_readiness_reminders(scheduled_job_id: str) -> None:
    """
    Registers the pre-window nudges alongside the staging trigger. Reminders
    whose time has already passed are skipped rather than fired late - a
    "save your Master List" alert arriving after the window is noise, and the
    handoff screen already marks those steps overdue.
    """
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, scheduled_job_id)
        if job is None:
            return

        now = datetime.now()
        scheduled = []
        for offset_seconds, message in _REMINDERS:
            run_at = job.window_open_time_ist - timedelta(seconds=offset_seconds)
            if run_at <= now:
                continue
            get_scheduler().add_job(
                _fire_reminder,
                "date",
                run_date=run_at,
                args=[scheduled_job_id, message],
                id=f"{scheduled_job_id}:reminder:{offset_seconds}",
                replace_existing=True,
                misfire_grace_time=MISFIRE_GRACE_SECONDS,
            )
            scheduled.append(offset_seconds)

        audit.log(
            db, agent="scheduler", action="readiness_reminders_registered", outcome="success",
            target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
            details={"offsets_seconds": scheduled, "skipped_as_past": len(_REMINDERS) - len(scheduled)},
        )
    finally:
        db.close()


async def _fire_reminder(scheduled_job_id: str, message: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, scheduled_job_id)
        if job is None or job.status not in ("pending", "staging", "staged_and_waiting"):
            return  # already booked, failed, or cancelled - nothing to prepare for
        notification_agent.send(db, message, level="action_required", scheduled_job_id=scheduled_job_id)
    finally:
        db.close()


async def _fire_staging(scheduled_job_id: str) -> None:
    """
    APScheduler callback (runs as a coroutine in the app's event loop via
    AsyncIOScheduler). Idempotent by job id: add_job(..., id=scheduled_job_id,
    replace_existing=True) means only one trigger is ever registered per job.
    """
    db = SessionLocal()
    try:
        job = db.get(models.ScheduledJob, scheduled_job_id)
        if job is None or job.status != "pending":
            audit.log(
                db, agent="scheduler", action="job_fire_skipped", outcome="rejected",
                target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
                details={"reason": "job missing or not in pending state"},
            )
            return

        try:
            await booking_agent.stage_job(db, job)
            notification_agent.send(
                db,
                f"Staging complete for job {job.id} on {job.target_platform}. "
                f"Go confirm now - CAPTCHA + final payment need you.",
                level="action_required",
                scheduled_job_id=job.id,
            )
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            db.add(job)
            db.commit()
            audit.log(
                db, agent="scheduler", action="job_fire_failed", outcome="error",
                target=scheduled_job_id, scheduled_job_id=scheduled_job_id,
                details={"error": str(exc)},
            )
            notification_agent.send(
                db, f"Staging FAILED for job {job.id}: {exc}", level="error", scheduled_job_id=job.id,
            )
    finally:
        db.close()
