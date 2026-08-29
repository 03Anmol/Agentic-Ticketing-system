from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import llm, models, schemas
from ..database import get_db
from ..agents import audit, orchestrator, search_progress

router = APIRouter(prefix="/api/journey", tags=["journey"])


@router.post("", response_model=schemas.JourneyRequestParsed)
def create_journey_request(payload: schemas.JourneyRequestIn, db: Session = Depends(get_db)):
    """FR-1: parse free text into structured fields, echo back for confirmation."""
    today_iso = datetime.utcnow().date().isoformat()
    parsed = llm.parse_journey_request(payload.text, today_iso)

    jr = models.JourneyRequest(
        raw_text=payload.text,
        origin=parsed.get("origin"),
        destination=parsed.get("destination"),
        travel_date=parsed.get("travel_date"),
        travel_class=parsed.get("travel_class"),
        quota=parsed.get("quota"),
        passenger_count=parsed.get("passenger_count", 1),
        status="pending_confirmation",
    )
    db.add(jr)
    db.commit()
    db.refresh(jr)

    audit.log(
        db, agent="orchestrator", action="journey_request_parsed", outcome="success",
        target=jr.id, journey_request_id=jr.id, details=parsed,
    )

    out = schemas.JourneyRequestParsed.model_validate(jr)
    out.needs_clarification = parsed.get("needs_clarification", False)
    out.clarification_note = parsed.get("clarification_note")
    return out


@router.post("/{journey_id}/confirm", response_model=schemas.JourneyResultsOut)
async def confirm_and_search(journey_id: str, payload: schemas.JourneyRequestConfirm, db: Session = Depends(get_db)):
    """
    User confirms/edits the parsed fields -> FR-2/FR-3/FR-4: fan out to
    search agents, merge + rank, summarize.
    """
    jr = db.get(models.JourneyRequest, journey_id)
    if jr is None:
        raise HTTPException(404, "journey request not found")

    for field in ("origin", "destination", "travel_date", "travel_class", "quota", "passenger_count"):
        value = getattr(payload, field)
        if value is not None:
            setattr(jr, field, value)

    if not jr.origin or not jr.destination or not jr.travel_date:
        raise HTTPException(400, "origin, destination and travel_date are required to search")

    jr.status = "searching"
    db.add(jr)
    db.commit()

    search_progress.start(jr.id)
    ranked: list[dict] = []
    platform_status: dict[str, str] = {}
    async for node_name, output in orchestrator.stream_search(
        jr.origin, jr.destination, jr.travel_date, jr.travel_class, jr.quota, payload.preferred_berth
    ):
        if "platform_status" in output:
            platform_status.update(output["platform_status"])
            search_progress.update(jr.id, output["platform_status"])
        if node_name == "compare":
            ranked = output["ranked"]
    search_progress.finish(jr.id)
    result = {"ranked": ranked, "platform_status": platform_status}

    # persist results
    db.query(models.TrainOption).filter(models.TrainOption.journey_request_id == jr.id).delete()
    option_rows = []
    for o in result["ranked"]:
        row = models.TrainOption(
            journey_request_id=jr.id,
            source_platform=o["source_platform"],
            train_no=o["train_no"],
            train_name=o["train_name"],
            departure_time=o["departure_time"],
            arrival_time=o["arrival_time"],
            duration_minutes=o["duration_minutes"],
            travel_class=o["travel_class"],
            quota=o["quota"],
            available_berths=o.get("available_berths", {}),
            fare=o["fare"],
            availability_status=o["availability_status"],
            rank_score=o["rank_score"],
        )
        db.add(row)
        option_rows.append(row)

    jr.status = "done"
    db.add(jr)
    db.commit()
    for row in option_rows:
        db.refresh(row)
    db.refresh(jr)

    summary = llm.summarize_results(
        {"origin": jr.origin, "destination": jr.destination, "date": jr.travel_date},
        result["ranked"],
    )

    audit.log(
        db, agent="comparison", action="search_completed", outcome="success",
        target=jr.id, journey_request_id=jr.id,
        details={"platform_status": result["platform_status"], "option_count": len(option_rows)},
    )

    return schemas.JourneyResultsOut(
        journey_request=schemas.JourneyRequestParsed.model_validate(jr),
        options=[schemas.TrainOptionOut.model_validate(r) for r in option_rows],
        summary=summary,
        platform_status=result["platform_status"],
    )


@router.get("/{journey_id}/progress")
def get_search_progress(journey_id: str):
    """Poll this while a /confirm search is in flight for a live status board."""
    return search_progress.get(journey_id)


@router.get("/{journey_id}", response_model=schemas.JourneyResultsOut)
def get_journey(journey_id: str, db: Session = Depends(get_db)):
    jr = db.get(models.JourneyRequest, journey_id)
    if jr is None:
        raise HTTPException(404, "journey request not found")
    options = db.query(models.TrainOption).filter(
        models.TrainOption.journey_request_id == jr.id
    ).order_by(models.TrainOption.rank_score).all()
    return schemas.JourneyResultsOut(
        journey_request=schemas.JourneyRequestParsed.model_validate(jr),
        options=[schemas.TrainOptionOut.model_validate(r) for r in options],
        summary=None,
        platform_status={},
    )


@router.get("", response_model=list[schemas.JourneyRequestParsed])
def list_journeys(db: Session = Depends(get_db)):
    rows = db.query(models.JourneyRequest).order_by(models.JourneyRequest.created_at.desc()).limit(50).all()
    return [schemas.JourneyRequestParsed.model_validate(r) for r in rows]
