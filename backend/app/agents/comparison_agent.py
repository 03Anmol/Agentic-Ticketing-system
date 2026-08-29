"""FRD FR-4: merge + rank TrainOptionDTOs from all platforms."""
from .base import TrainOptionDTO

_AVAILABILITY_RANK = {
    "AVAILABLE": 0,
}


def _availability_rank(status: str) -> int:
    if status in _AVAILABILITY_RANK:
        return _AVAILABILITY_RANK[status]
    if status.startswith("RAC"):
        return 100 + int(status.split()[-1])
    if status.startswith("WL"):
        return 1000 + int(status.split()[-1])
    return 5000


def rank_options(options: list[TrainOptionDTO], preferred_berth: str | None = None) -> list[dict]:
    """
    Returns dicts sorted best-first: confirmed availability first, then price,
    then duration. If preferred_berth is set (e.g. "LOWER"), options that
    actually have that berth type available are boosted to the top of their
    availability tier - this is display/ranking only, no booking action.
    """
    scored = []
    for o in options:
        avail_rank = _availability_rank(o.availability_status)
        # lower is better; combine availability (dominant), then fare, then duration
        score = avail_rank * 1_000_000 + o.fare * 10 + o.duration_minutes
        if preferred_berth and o.available_berths.get(preferred_berth, 0) > 0:
            score -= 500_000  # keep within the same availability tier, jump ahead of non-matches
        d = o.to_dict()
        d["rank_score"] = score
        scored.append(d)
    scored.sort(key=lambda d: d["rank_score"])
    return scored
