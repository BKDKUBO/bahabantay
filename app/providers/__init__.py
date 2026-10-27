import os
from .mock import MockVision, MockReports, MockAgent
from .meta import MetaVision, MetaReports, MetaAgent, load_dotenv


def get_providers(name: str | None = None):
    """Returns (vision, reports, agent)."""
    load_dotenv()
    name = (name or os.getenv("BAHABANTAY_PROVIDER", "mock")).lower()
    if name == "mock":
        return MockVision(), MockReports(), MockAgent()
    if name == "meta":
        return MetaVision(), MetaReports(), MetaAgent()
    raise ValueError(f"unknown provider {name!r}")
