from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class JourneyRequestIn(BaseModel):
    text: str


class JourneyRequestParsed(BaseModel):
    id: str
    raw_text: str
    origin: Optional[str] = None
    destination: Optional[str] = None
    travel_date: Optional[str] = None
    travel_class: Optional[str] = None
    quota: Optional[str] = None
    passenger_count: int = 1
    status: str
    needs_clarification: bool = False
    clarification_note: Optional[str] = None

    class Config:
        from_attributes = True


class JourneyRequestConfirm(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    travel_date: Optional[str] = None
    travel_class: Optional[str] = None
    quota: Optional[str] = None
    passenger_count: Optional[int] = None
    preferred_berth: Optional[str] = None  # LOWER / MIDDLE / UPPER / SIDE_LOWER / SIDE_UPPER


class TrainOptionOut(BaseModel):
    id: str
    source_platform: str
    train_no: str
    train_name: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    travel_class: str
    quota: str
    fare: float
    availability_status: str
    available_berths: dict[str, int] = {}
    rank_score: float

    class Config:
        from_attributes = True


class JourneyResultsOut(BaseModel):
    journey_request: JourneyRequestParsed
    options: list[TrainOptionOut]
    summary: Optional[str] = None
    platform_status: dict[str, str] = {}


class PassengerProfileIn(BaseModel):
    name: str
    age: int
    gender: str
    berth_preference: Optional[str] = None
    id_proof_ref: Optional[str] = None


class PassengerProfileOut(PassengerProfileIn):
    id: str

    class Config:
        from_attributes = True


class ScheduledJobIn(BaseModel):
    journey_request_id: str
    train_option_id: str
    target_platform: str
    window_open_time_ist: datetime
    lead_time_seconds: int = 120

    @field_validator("window_open_time_ist")
    @classmethod
    def _normalize_to_naive_local(cls, v: datetime) -> datetime:
        """
        Browsers send `new Date(...).toISOString()`, which is always UTC with
        a 'Z' suffix - a timezone-AWARE value. Everything else in this app
        (the scheduler, guardrail token expiry, datetime.now() checks) uses
        naive local-system-time datetimes, per the FRD's stated assumption
        that the host clock is IST. Mixing aware and naive datetimes raises
        TypeError on comparison (the actual cause of the 500 this was added
        to fix) - astimezone() with no args converts to the system's local
        zone, so the wall-clock value stays correct instead of just having
        its tzinfo silently stripped (which would shift it by the UTC offset).
        """
        if v.tzinfo is not None:
            v = v.astimezone().replace(tzinfo=None)
        return v


class ImmediateJobIn(BaseModel):
    journey_request_id: str
    train_option_id: str
    target_platform: str


class ScheduledJobOut(BaseModel):
    id: str
    journey_request_id: str
    train_option_id: Optional[str]
    target_platform: str
    window_open_time_ist: datetime
    lead_time_seconds: int
    status: str
    booking_mode: str = "scheduled"
    pnr: Optional[str] = None
    booked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConfirmationTokenOut(BaseModel):
    id: str
    scheduled_job_id: str
    expires_at: datetime


class NotificationOut(BaseModel):
    id: str
    created_at: datetime
    scheduled_job_id: Optional[str]
    message: str
    level: str
    seen: bool

    class Config:
        from_attributes = True


class CompleteBookingIn(BaseModel):
    token_id: str


class RecordPnrIn(BaseModel):
    pnr: str


class ChecklistStepIn(BaseModel):
    step_key: str
    done: bool = True


class AuditLogOut(BaseModel):
    id: str
    timestamp: datetime
    agent: str
    action: str
    target: Optional[str]
    outcome: str
    details: Optional[dict] = None

    class Config:
        from_attributes = True
