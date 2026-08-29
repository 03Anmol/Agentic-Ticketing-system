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

    async def search(
        self,
        origin: str,
        destination: str,
        travel_date: str,
        travel_class: str | None,
        quota: str | None,
    ) -> list[TrainOptionDTO]:
        ...
