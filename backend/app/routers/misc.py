from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/notifications", response_model=list[schemas.NotificationOut])
def list_notifications(db: Session = Depends(get_db)):
    return db.query(models.Notification).order_by(models.Notification.created_at.desc()).limit(50).all()


@router.post("/notifications/{notification_id}/seen", response_model=schemas.NotificationOut)
def mark_seen(notification_id: str, db: Session = Depends(get_db)):
    note = db.get(models.Notification, notification_id)
    if note is None:
        raise HTTPException(404, "notification not found")
    note.seen = True
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/audit", response_model=list[schemas.AuditLogOut])
def list_audit(db: Session = Depends(get_db)):
    return db.query(models.AuditLogEntry).order_by(models.AuditLogEntry.timestamp.desc()).limit(200).all()


@router.get("/passengers", response_model=list[schemas.PassengerProfileOut])
def list_passengers(db: Session = Depends(get_db)):
    return db.query(models.PassengerProfile).all()


@router.post("/passengers", response_model=schemas.PassengerProfileOut)
def create_passenger(payload: schemas.PassengerProfileIn, db: Session = Depends(get_db)):
    row = models.PassengerProfile(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/passengers/{passenger_id}")
def delete_passenger(passenger_id: str, db: Session = Depends(get_db)):
    row = db.get(models.PassengerProfile, passenger_id)
    if row is None:
        raise HTTPException(404, "passenger not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
