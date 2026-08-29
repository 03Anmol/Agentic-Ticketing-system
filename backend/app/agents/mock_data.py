"""
Deterministic mock train data generator, shared by all three platform
search agents until real adapters are wired in.

WHY THIS IS A STUB (read before replacing):
  IRCTC, ixigo, and ConfirmTkt have no general-purpose public search API,
  and this session had no way to verify a live scraping path against their
  actual pages/ToS. Rather than ship an unverified scraper that might break
  on first run or violate a platform's terms, each platform agent below
  returns realistic-shaped mock data through this shared generator, seeded
  deterministically from the query so results are stable and comparable
  across platforms/runs.

TO GO LIVE, per platform (see FRD FR-3):
  1. Check for an official/partner API first (this is how ixigo and
     ConfirmTkt themselves operate against IRCTC - they are licensed
     agents, not scrapers).
  2. If none exists and you fall back to reading the platform's own public
     search page, confirm its ToS/robots.txt permit automated access, and
     keep it strictly read-only (search/availability), never touching the
     booking/payment flow (that stays behind the FR-7 human-confirmation
     gate regardless).
  3. Implement `search()` in the corresponding agent file with the same
     TrainOptionDTO return shape - nothing else in the system needs to
     change.

TRAIN IDENTITIES (numbers/names): if DATA_GOV_IN_API_KEY and
DATA_GOV_IN_TRAIN_RESOURCE_ID are configured (see agents/real_train_catalog.py),
the catalog below is real train numbers/names fetched live from India's open
government data portal instead of the static fallback list. Departure time,
duration, fare and availability stay simulated regardless - that dataset is
a stop-by-stop time table, not a live seat-availability feed, and no such
feed can legally be scraped per docs/AUTOMATION_LIMITS.md.
"""
import hashlib
from datetime import datetime, timedelta

from .base import TrainOptionDTO
from . import real_train_catalog

_TRAIN_CATALOG = [
    ("12951", "Mumbai Rajdhani", 16 * 60 + 35, 8 * 60 + 35),
    ("12301", "Howrah Rajdhani", 16 * 60 + 55, 9 * 60 + 55),
    ("12621", "Tamil Nadu Express", 22 * 60 + 30, 7 * 60 + 15),
    ("12009", "Shatabdi Express", 6 * 60 + 0, 13 * 60 + 30),
    ("12269", "Duronto Express", 23 * 60 + 45, 15 * 60 + 20),
    ("12137", "Punjab Mail", 19 * 60 + 40, 10 * 60 + 5),
]


def _active_catalog() -> list[tuple[str, str, int, int]]:
    """Real train_no/train_name from data.gov.in when configured, paired with
    the static list's synthetic timing slots; falls back to fully static."""
    real = real_train_catalog.get_real_trains()
    if not real:
        return _TRAIN_CATALOG
    catalog = [
        (real[i]["train_no"], real[i]["train_name"], dep_min, dur_min)
        for i, (_, _, dep_min, dur_min) in enumerate(_TRAIN_CATALOG)
        if i < len(real)
    ]
    return catalog or _TRAIN_CATALOG

_CLASSES = ["1A", "2A", "3A", "SL", "CC"]
_AVAILABILITY_POOL = ["AVAILABLE", "AVAILABLE", "RAC 3", "RAC 8", "WL 4", "WL 22"]
_BERTH_TYPES = ["LOWER", "MIDDLE", "UPPER", "SIDE_LOWER", "SIDE_UPPER"]


def _mock_berth_counts(seed: int, availability: str) -> dict[str, int]:
    """
    Per-berth-type mock counts. Real IRCTC only exposes this level of detail
    once you're inside the booking flow (not at search time), so this is
    illustrative, not a claim of real per-berth availability - the point is
    to let the UI show/rank by berth preference without needing any login.
    """
    if availability.startswith("WL"):
        return {b: 0 for b in _BERTH_TYPES}
    counts = {}
    for j, berth in enumerate(_BERTH_TYPES):
        counts[berth] = (seed >> (j * 3)) % 5  # 0-4, deterministic per berth
    return counts


def _seed_int(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16)


def generate_mock_trains(
    platform: str,
    origin: str,
    destination: str,
    travel_date: str,
    travel_class: str | None,
    quota: str | None,
    fare_multiplier: float,
) -> list[TrainOptionDTO]:
    base_seed = _seed_int(platform, origin, destination, travel_date)
    options: list[TrainOptionDTO] = []

    for i, (train_no, train_name, dep_min, dur_min) in enumerate(_active_catalog()):
        seed = base_seed + i
        cls = travel_class or _CLASSES[seed % len(_CLASSES)]
        base_fare = 400 + (seed % 2200)
        fare = round(base_fare * fare_multiplier * (1.6 if cls in ("1A", "2A") else 1.0), 2)
        availability = _AVAILABILITY_POOL[(seed // 7) % len(_AVAILABILITY_POOL)]

        try:
            date_obj = datetime.strptime(travel_date, "%Y-%m-%d")
        except ValueError:
            date_obj = datetime.utcnow()
        dep_dt = date_obj + timedelta(minutes=dep_min)
        arr_dt = dep_dt + timedelta(minutes=dur_min)

        options.append(
            TrainOptionDTO(
                source_platform=platform,
                train_no=train_no,
                train_name=train_name,
                departure_time=dep_dt.strftime("%Y-%m-%d %H:%M"),
                arrival_time=arr_dt.strftime("%Y-%m-%d %H:%M"),
                duration_minutes=dur_min,
                travel_class=cls,
                quota=quota or "GENERAL",
                fare=fare,
                availability_status=availability,
                available_berths=_mock_berth_counts(seed, availability),
            )
        )
    return options
