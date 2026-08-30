from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from . import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (ensure models are registered on Base)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


# Columns added after the first release. create_all() only ever CREATEs - it
# will not ALTER a table that already exists, so an existing ticket_agent.db
# would keep the old schema and every query naming a new column would fail.
# This project is single-user with a disposable SQLite file, so a full
# migration tool (Alembic) would be more machinery than the problem needs;
# this does the one thing required, idempotently.
_EXPECTED_COLUMNS = {
    "scheduled_jobs": {
        "pnr": "VARCHAR",
        "booked_at": "DATETIME",
        "booking_mode": "VARCHAR DEFAULT 'scheduled'",
        "checklist_progress": "JSON",
    },
}


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _EXPECTED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all just made it with the full schema
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
