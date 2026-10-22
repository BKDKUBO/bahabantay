"""STUB Meta provider. Fill in once hackathon access + API credits arrive (Oct 26+).

Do NOT add credentials to this repo. Read them from env vars at runtime
(e.g. META_API_KEY) and keep them out of git.
"""
from __future__ import annotations
from .base import Segmentation


class MetaVision:
    name = "meta"

    def segment(self, image: bytes, prompts: list[str]) -> Segmentation:
        # TODO(meta): call SAM 3.1 promptable concept segmentation via the Meta
        #   model API with text prompts ["water", "person", "door", "car tire", ...].
        # TODO(meta): convert returned masks to Mask(label, bbox, score); keep the
        #   raw mask PNG so the UI can overlay it for responders to verify.
        # TODO(meta): timeouts, retries, and fall back to MockVision on failure in demo mode.
        raise NotImplementedError("Meta SAM 3.1 provider not implemented yet (no API access).")


    def track_frames(self, frames: list[bytes], prompts: list[str]) -> list[Segmentation]:
        # TODO(meta): use SAM 3.1 video / multi-frame tracking via the Meta model API
        #   to follow the same water surface + reference object across a short clip
        #   or several photos of one spot, giving a per-frame waterline for trend.
        raise NotImplementedError("Meta SAM 3.1 video tracking not implemented yet (no API access).")


class MetaAgent:
    name = "meta"

    def run(self, report: dict, tools) -> dict:
        # TODO(meta): Muse Spark tool-calling loop over tools.get_nearby_reports,
        #   tools.merge_duplicates, tools.flag_people_at_risk, tools.ask_followup.
        raise NotImplementedError("Meta Muse Spark agent not implemented yet (no API access).")


class MetaReports:
    name = "meta"

    def situation_report(self, summary: dict, lang: str) -> str:
        # TODO(meta): call Muse Spark via the Meta model API with the aggregated
        #   street summary as JSON plus a system prompt for a BDRRMO bulletin in
        #   Filipino ("fil") or English ("en").
        # TODO(meta): tool-calling agent: segment, estimate_depth, nearby_reports,
        #   flag_people_at_risk, draft_bulletin(lang).
        raise NotImplementedError("Meta Muse Spark provider not implemented yet (no API access).")
