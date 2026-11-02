"""Provider interface for every Meta model call (SAM 3.1 + Muse Spark).

Nothing outside app/providers talks to a model directly. Swap providers with
the BAHABANTAY_PROVIDER env var: "mock" (default) or "meta".
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Mask:
    label: str            # "water", "person", "door", "car_tire", ...
    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1 as 0..1 fractions
    score: float


@dataclass
class Segmentation:
    masks: list[Mask] = field(default_factory=list)
    source: str = ""    # provider that actually produced this: "meta", "mock", or "mock-fallback"

    def of(self, label: str) -> list[Mask]:
        return [m for m in self.masks if m.label == label]


class VisionProvider(Protocol):
    name: str
    def segment(self, image: bytes, prompts: list[str]) -> Segmentation: ...
    def track_frames(self, frames: list[bytes], prompts: list[str]) -> list[Segmentation]: ...


class ReportProvider(Protocol):
    name: str
    def situation_report(self, summary: dict, lang: str) -> str: ...
    def answer(self, summary: dict, question: str, lang: str) -> dict: ...
    def extract(self, note: str, est: dict) -> dict: ...
    def advisory(self, facts: dict) -> dict: ...


class AgentProvider(Protocol):
    """Runs the report-triage agent. `tools` is an app.agent.Tools instance."""
    name: str
    def run(self, report: dict, tools) -> dict: ...
