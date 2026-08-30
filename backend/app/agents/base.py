"""
FRD S3 (FR-3): common Search Agent interface. Every platform adapter
implements `search()` with this exact signature so the Orchestrator and
Comparison Agent never need to know which platform they're talking to.
"""
from dataclasses import dataclass, asdict
from typing import Protocol


@dataclass
class TrainOptionDTO:
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
    available_berths: dict[str, int]

    def to_dict(self) -> dict:
        return asdict(self)


class SearchAgent(Protocol):
    platform_name: str

    # False while the adapter returns generated data. The pipeline carries this
    # all the way to the UI so a simulated fare is never displayed as though it
    # were a real quote - showing "Rs 888.89, AVAILABLE" for a train that isn't
    # actually on the route is worse than showing nothing, because it looks
    # authoritative. Flip to True in the adapter when a real API is wired in.
    is_live: bool

    async def search(
        self,
        origin: str,
        destination: str,
        travel_date: str,
        travel_class: str | None,
        quota: str | None,
    ) -> list[TrainOptionDTO]:
        ...
