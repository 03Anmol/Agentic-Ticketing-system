"""
In-memory, single-process store of live per-platform search status, keyed by
journey_request_id. Lets the frontend poll GET /api/journey/{id}/progress
while the POST /confirm search is still in flight, so the status board
updates as each platform finishes instead of appearing all at once at the
end. Not persisted - a restart mid-search just means the poller sees
"unknown" until the next search, which is fine since it's UI-only state.
"""
_progress: dict[str, dict] = {}


def start(journey_id: str) -> None:
    _progress[journey_id] = {"platform_status": {}, "done": False}


def update(journey_id: str, platform_status: dict[str, str]) -> None:
    entry = _progress.setdefault(journey_id, {"platform_status": {}, "done": False})
    entry["platform_status"].update(platform_status)


def finish(journey_id: str) -> None:
    entry = _progress.setdefault(journey_id, {"platform_status": {}, "done": False})
    entry["done"] = True


def get(journey_id: str) -> dict:
    return _progress.get(journey_id, {"platform_status": {}, "done": False})
