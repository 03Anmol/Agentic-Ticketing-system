import asyncio

from .base import TrainOptionDTO
from .mock_data import generate_mock_trains


class IxigoSearchAgent:
    """STUB adapter - see mock_data.py docstring for what's needed to go live."""

    platform_name = "ixigo"

    async def search(
        self,
        origin: str,
        destination: str,
        travel_date: str,
        travel_class: str | None,
        quota: str | None,
    ) -> list[TrainOptionDTO]:
        await asyncio.sleep(0.4)
        return generate_mock_trains(
            self.platform_name, origin, destination, travel_date, travel_class, quota,
            fare_multiplier=1.04,  # small convenience fee, matches ixigo being an IRCTC agent
        )
