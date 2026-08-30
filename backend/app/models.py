import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id() -> str:
    return uuid.uuid4().hex


class PassengerProfile(Base):
    __tablename__ = "passenger_profiles"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)
    berth_preference = Column(String, nullable=True)
    id_proof_ref = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JourneyRequest(Base):
    __tablename__ = "journey_requests"

    id = Column(String, primary_key=True, default=gen_id)
    raw_text = Column(Text, nullable=False)

    origin = Column(String, nullable=True)
    destination = Column(String, nullable=True)
    travel_date = Column(String, nullable=True)  # ISO date string, IST calendar date
    travel_class = Column(String, nullable=True)
    quota = Column(String, nullable=True)
    passenger_count = Column(Integer, default=1)

    # pending_confirmation -> confirmed -> searching -> done/failed
    status = Column(String, default="pending_confirmation")

    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("TrainOption", back_populates="journey_request", cascade="all, delete-orphan")
    scheduled_jobs = relationship("ScheduledJob", back_populates="journey_request", cascade="all, delete-orphan")


class TrainOption(Base):
    __tablename__ = "train_options"

    id = Column(String, primary_key=True, default=gen_id)
    journey_request_id = Column(String, ForeignKey("journey_requests.id"), nullable=False)

    source_platform = Column(String, nullable=False)
    train_no = Column(String, nullable=False)
    train_name = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    arrival_time = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    travel_class = Column(String, nullable=False)
    quota = Column(String, nullable=False)
    fare = Column(Float, nullable=False)
    availability_status = Column(String, nullable=False)  # e.g. "AVAILABLE", "RAC 4", "WL 12"
    available_berths = Column(JSON, nullable=True)  # e.g. {"LOWER": 3, "MIDDLE": 5, ...}
    rank_score = Column(Float, default=0.0)

    journey_request = relationship("JourneyRequest", back_populates="results")


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(String, primary_key=True, default=gen_id)
    journey_request_id = Column(String, ForeignKey("journey_requests.id"), nullable=False)
    train_option_id = Column(String, ForeignKey("train_options.id"), nullable=True)

    target_platform = Column(String, nullable=False)
    window_open_time_ist = Column(DateTime, nullable=False)
    lead_time_seconds = Column(Integer, default=120)

    # 'scheduled' = wait for a Tatkal window (the reason this table exists).
    # 'immediate' = book right now; there is no window to wait for, so no
    # scheduler entry and no pre-window reminders are registered. Normal
    # (non-Tatkal) booking is this mode, and it's the common case - the UI
    # originally offered only the scheduled path, which forced users to invent
    # a fake window time for bookings that had none.
    booking_mode = Column(String, default="scheduled")

    # pending -> staging -> staged_and_waiting -> confirmed / expired / failed
    status = Column(String, default="pending")

    # {step_key: ISO timestamp} for each Launch Pad step the user has ticked
    # off. Persisted rather than kept in the page so progress survives a
    # refresh, a browser restart, or picking the job back up on another device
    # - a Tatkal prep run starts 30 minutes before the window, which is long
    # enough for any of those to happen.
    checklist_progress = Column(JSON, nullable=True)

    # Set by the user after they complete the booking themselves on IRCTC
    # (POST /api/jobs/{id}/pnr). This is the only record of a REAL booking in
    # the system - job.status='confirmed' only ever reflects this app's own
    # mock flow, never a live railway transaction.
    pnr = Column(String, nullable=True)
    booked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    journey_request = relationship("JourneyRequest", back_populates="scheduled_jobs")
    confirmation_tokens = relationship("ConfirmationToken", back_populates="scheduled_job", cascade="all, delete-orphan")


class ConfirmationToken(Base):
    __tablename__ = "confirmation_tokens"

    id = Column(String, primary_key=True, default=gen_id)
    scheduled_job_id = Column(String, ForeignKey("scheduled_jobs.id"), nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)

    scheduled_job = relationship("ScheduledJob", back_populates="confirmation_tokens")


class Notification(Base):
    """
    FR-8. No SMS/push provider is wired up in this build (PRD S13 leaves the
    channel as an open question) - this table + GET /api/notifications is the
    stand-in "webhook-ish" channel the frontend polls, and is where a real
    push/SMS/email sender would also be triggered from.
    """
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_id)
    created_at = Column(DateTime, default=datetime.utcnow)
    scheduled_job_id = Column(String, ForeignKey("scheduled_jobs.id"), nullable=True)
    message = Column(String, nullable=False)
    level = Column(String, default="info")  # info / action_required / error
    seen = Column(Boolean, default=False)


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=gen_id)
    timestamp = Column(DateTime, default=datetime.utcnow)
    agent = Column(String, nullable=False)
    action = Column(String, nullable=False)
    target = Column(String, nullable=True)
    outcome = Column(String, nullable=False)  # success / rejected / error
    details = Column(JSON, nullable=True)
    related_journey_request_id = Column(String, nullable=True)
    related_scheduled_job_id = Column(String, nullable=True)
