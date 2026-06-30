"""Wearable provider boundary used by the dashboard."""

from dataclasses import dataclass
from typing import Protocol

from database.repository import seed_mock_wearable


@dataclass(frozen=True)
class WearableConnection:
    provider: str
    connected: bool
    source: str


class WearableProvider(Protocol):
    def sync(self, participant_id: str) -> WearableConnection:
        """Synchronise wearable observations for one participant."""


class DemoWearableProvider:
    """Deterministic adapter that can later be replaced by an OAuth provider."""

    def sync(self, participant_id: str) -> WearableConnection:
        seed_mock_wearable(participant_id)
        return WearableConnection("Oura demo", True, "mock")


SUPPORTED_PROVIDERS = ("Fitbit", "Oura Ring", "Garmin", "Apple Health", "Google Fit")

