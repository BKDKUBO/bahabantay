import os
from .mock import MockVision, MockReports, MockAgent
from .meta import MetaVision, MetaReports, MetaAgent


def get_providers(name: str | None = None):
    """Returns (vision, reports, agent)."""
    name = (name or os.getenv("BAHABANTAY_PROVIDER", "mock")).lower()
    if name == "mock":
        return MockVision(), MockReports(), MockAgent()
    if name == "meta":
        return MetaVision(), MetaReports(), MetaAgent()
    raise ValueError(f"unknown provider {name!r}")
