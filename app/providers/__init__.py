import os
from .mock import MockVision, MockReports
from .meta import MetaVision, MetaReports


def get_providers(name: str | None = None):
    name = (name or os.getenv("BAHABANTAY_PROVIDER", "mock")).lower()
    if name == "mock":
        return MockVision(), MockReports()
    if name == "meta":
        return MetaVision(), MetaReports()
    raise ValueError(f"unknown provider {name!r}")
