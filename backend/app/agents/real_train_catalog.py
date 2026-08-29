"""
Real train identities (numbers/names) from data.gov.in's Indian Railways
Train Time Table dataset - a genuinely public, government-published, open-
for-reuse dataset (unlike irctc.co.in/ixigo.com/confirmtkt.com - see
docs/AUTOMATION_LIMITS.md for why those stay off-limits).

WHY THIS DEGRADES GRACEFULLY INSTEAD OF ASSERTING A SCHEMA:
  data.gov.in blocked this session's automated fetch of the dataset's own
  catalog page (403), and search results didn't surface the dataset's exact
  resource ID or field names. Both are needed to call the API and parse its
  response, and both are things you can get in about a minute by visiting
  the dataset's page yourself:
    1. Sign up for a free key: https://api.data.gov.in/signup/
    2. Open https://www.data.gov.in/catalog/indian-railways-train-time-table
       (or search "Indian Railways" on data.gov.in) and click its "API"
       button/tab - it shows the resource ID and a working sample call.
    3. Put both in .env as DATA_GOV_IN_API_KEY / DATA_GOV_IN_TRAIN_RESOURCE_ID.

  Rather than guess the resource ID (very likely wrong, and would look like
  it works while silently returning nothing) or hardcode field names I
  haven't seen a real response for, this module tries several field-name
  variants seen across similar Indian-government transport datasets, and
  if none match, LOGS THE ACTUAL FIELD NAMES IT FOUND so they can be added
  below in two minutes - then falls back to the static catalog rather than
  crash the search flow either way.

WHAT THIS DOES AND DOESN'T GET YOU:
  - DOES give real train numbers/names, fetched live from a real government
    dataset, replacing the fictional catalog in mock_data.py.
  - Does NOT give real per-route timing, fare, or seat availability for
    those trains - the time-table dataset is a full stop-by-stop schedule,
    not a "search trains between station A and B" endpoint, and correlating
    it into that shape reliably needs the verified field names above. Those
    stay simulated, same as before, just attached to real train identities.
"""
import json
import logging
import time
import urllib.parse
import urllib.request

from .. import config

logger = logging.getLogger("ticket_agent.real_catalog")

_CACHE: dict = {"trains": None, "fetched_at": 0.0}
_CACHE_TTL_SECONDS = 24 * 60 * 60
_FETCH_TIMEOUT_SECONDS = 10

_TRAIN_NO_FIELDS = ["train_no", "Train_No", "train_number", "TRAIN_NO", "Train_No.", "train_no."]
_TRAIN_NAME_FIELDS = ["train_name", "Train_Name", "TRAIN_NAME"]
_SOURCE_FIELDS = ["source_stn_name", "Source_Station", "source_station_name", "SOURCE_STATION_NAME"]
_DEST_FIELDS = ["destination_stn_name", "Destination_Station", "destination_station_name", "DESTINATION_STATION_NAME"]


def is_configured() -> bool:
    return bool(config.DATA_GOV_IN_API_KEY and config.DATA_GOV_IN_TRAIN_RESOURCE_ID)


def _first_present(record: dict, candidates: list[str]) -> str | None:
    for key in candidates:
        if record.get(key):
            return str(record[key])
    return None


def _fetch_raw(limit: int) -> list[dict] | None:
    params = urllib.parse.urlencode({
        "api-key": config.DATA_GOV_IN_API_KEY,
        "format": "json",
        "limit": limit,
    })
    url = f"https://api.data.gov.in/resource/{config.DATA_GOV_IN_TRAIN_RESOURCE_ID}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        logger.exception("Failed to reach data.gov.in for the live train catalog")
        return None

    records = data.get("records", [])
    if not records:
        logger.warning(
            "data.gov.in returned zero records - check DATA_GOV_IN_TRAIN_RESOURCE_ID is correct "
            "for the 'Indian Railways Train Time Table' dataset."
        )
        return None
    return records


def get_real_trains(limit: int = 500) -> list[dict] | None:
    """
    Returns [{"train_no", "train_name", "source", "destination"}, ...] deduped
    by train_no, or None if unconfigured/unreachable/schema-mismatched - in
    every None case the caller (mock_data.py) falls back to the static list.
    """
    if not is_configured():
        return None

    now = time.time()
    if _CACHE["trains"] is not None and (now - _CACHE["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _CACHE["trains"]

    raw = _fetch_raw(limit)
    if raw is None:
        return None

    parsed: list[dict] = []
    unmatched_sample_keys = None
    for record in raw:
        train_no = _first_present(record, _TRAIN_NO_FIELDS)
        train_name = _first_present(record, _TRAIN_NAME_FIELDS)
        if not train_no or not train_name:
            if unmatched_sample_keys is None:
                unmatched_sample_keys = list(record.keys())
            continue
        parsed.append({
            "train_no": train_no,
            "train_name": train_name,
            "source": _first_present(record, _SOURCE_FIELDS),
            "destination": _first_present(record, _DEST_FIELDS),
        })

    if not parsed:
        logger.warning(
            "None of this session's known field-name guesses matched the live response. "
            "Actual field names seen: %s. Add the right ones to _TRAIN_NO_FIELDS / "
            "_TRAIN_NAME_FIELDS in real_train_catalog.py - falling back to the static catalog "
            "until then.",
            unmatched_sample_keys,
        )
        return None

    by_no: dict[str, dict] = {}
    for t in parsed:
        by_no.setdefault(t["train_no"], t)
    result = list(by_no.values())

    _CACHE["trains"] = result
    _CACHE["fetched_at"] = now
    logger.info("Loaded %d real train identities from data.gov.in", len(result))
    return result
