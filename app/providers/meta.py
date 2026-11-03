"""Meta Model API provider: SAM 3.1 (vision) + Muse Spark (agent + sitrep).

Credentials come from META_API_KEY or MODEL_API_KEY at runtime — never committed.
On API/network/parse failure, falls back to the mock provider when
BAHABANTAY_META_FALLBACK is true (default).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

from .base import Mask, Segmentation
from .mock import MockAgent, MockReports, MockVision
from .. import qa

log = logging.getLogger("bahabantay.meta")

# Visible fallback accounting: /api/health reports these so the UI can say when mock answered.
FALLBACKS = {"count": 0, "last": None}


def _note_fallback(where: str, e: Exception) -> None:
    from datetime import datetime, timezone
    FALLBACKS["count"] += 1
    FALLBACKS["last"] = {"where": where, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": type(e).__name__}
    log.warning("%s failed (%s); falling back to mock", where, e)

BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = "sam-3.1"
MUSE_MODEL = "muse-spark-1.3"

# Our internal labels -> SAM noun-phrase prompts
PROMPT_TEXT = {
    "water": "water",
    "person": "person",
    "door": "door",
    "car_tire": "car tire",
    "jeepney": "jeepney",
    "curb": "curb",
}

# Reverse: phrase / alias -> our label
LABEL_ALIASES = {
    "water": "water",
    "flood water": "water",
    "floodwater": "water",
    "person": "person",
    "people": "person",
    "human": "person",
    "door": "door",
    "car tire": "car_tire",
    "tire": "car_tire",
    "car_tire": "car_tire",
    "jeepney": "jeepney",
    "curb": "curb",
}

_BOX_RE = re.compile(
    r"<\|box;"
    r"x1=(?P<x1>[\d.]+);y1=(?P<y1>[\d.]+);"
    r"x2=(?P<x2>[\d.]+);y2=(?P<y2>[\d.]+);"
    r"w=(?P<w>[\d.]+);h=(?P<h>[\d.]+)"
    r"(?:;c=(?P<c>[\d.]+))?"
    r"\|>"
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Lightweight .env loader. Does not overwrite existing env vars. No extra dep."""
    env_path = path or (_project_root() / ".env")
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def _fallback_enabled() -> bool:
    return os.getenv("BAHABANTAY_META_FALLBACK", "true").lower() not in ("0", "false", "no")


def _api_key() -> str | None:
    load_dotenv()
    key = os.getenv("META_API_KEY") or os.getenv("MODEL_API_KEY") or None
    if key is not None and not str(key).strip():
        return None
    return key


def get_client():
    """Shared OpenAI-compatible client pointed at Meta Model API."""
    key = _api_key()
    if not key:
        raise RuntimeError(
            "META_API_KEY or MODEL_API_KEY is required for the meta provider "
            "(set BAHABANTAY_META_FALLBACK=true to use mock on missing key)."
        )
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=key)


def _data_url(image: bytes) -> str:
    mime = "image/png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def normalize_label(prompt: str) -> str:
    p = (prompt or "").strip().lower().replace("_", " ")
    if p in LABEL_ALIASES:
        return LABEL_ALIASES[p]
    underscored = p.replace(" ", "_")
    return LABEL_ALIASES.get(underscored, underscored)


def prompt_phrase(label: str) -> str:
    lab = normalize_label(label)
    return PROMPT_TEXT.get(lab, lab.replace("_", " "))


def parse_sam_output_text(text: str, label: str) -> list[Mask]:
    """Parse SAM 3.1 special-token output into Masks (bbox fractions; mask raster optional)."""
    lab = normalize_label(label)
    masks: list[Mask] = []
    if not (text or "").strip():
        return masks
    for m in _BOX_RE.finditer(text):
        w = float(m.group("w")) or 1.0
        h = float(m.group("h")) or 1.0
        x1, y1 = float(m.group("x1")) / w, float(m.group("y1")) / h
        x2, y2 = float(m.group("x2")) / w, float(m.group("y2")) / h
        # clamp to 0..1
        x1, y1 = max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1))
        x2, y2 = max(0.0, min(1.0, x2)), max(0.0, min(1.0, y2))
        score = float(m.group("c")) if m.group("c") is not None else 0.85
        masks.append(Mask(lab, (x1, y1, x2, y2), score))
    return masks


def _collect_output_text(stream) -> str:
    chunks: list[str] = []
    done_text = ""
    for event in stream:
        et = getattr(event, "type", None)
        if et == "response.output_text.delta":
            delta = getattr(event, "delta", None)
            if delta:
                chunks.append(delta)
        elif et == "response.output_text.done":
            t = getattr(event, "text", None)
            if t:
                done_text = t
        elif et == "response.completed":
            resp = getattr(event, "response", None)
            ot = getattr(resp, "output_text", None) if resp is not None else None
            if ot and not chunks and not done_text:
                return ot
    return "".join(chunks) or done_text


def _sam_one(client, image_url: str, phrase: str) -> str:
    stream = client.responses.create(
        model=SAM_MODEL,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": phrase},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
        stream=True,
        metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
    )
    return _collect_output_text(stream)


def _muse_chat(client, messages: list[dict], **kw) -> str:
    resp = client.chat.completions.create(model=MUSE_MODEL, messages=messages, **kw)
    return (resp.choices[0].message.content or "").strip()


class MetaVision:
    name = "meta"

    def segment(self, image: bytes, prompts: list[str]) -> Segmentation:
        try:
            client = get_client()
            url = _data_url(image)
            masks: list[Mask] = []
            for p in prompts:
                phrase = prompt_phrase(p)
                label = normalize_label(p)
                text = _sam_one(client, url, phrase)
                masks.extend(parse_sam_output_text(text, label))
            return Segmentation(masks, source="meta")
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("SAM 3.1 segment", e)
            seg = MockVision().segment(image, prompts); seg.source = "mock-fallback"; return seg

    def track_frames(self, frames: list[bytes], prompts: list[str]) -> list[Segmentation]:
        try:
            # Per-frame segment (data URLs); SAM video tracking can replace this later.
            return [self.segment(f, prompts) for f in frames]
        except Exception as e:
            if not _fallback_enabled():
                raise
            log.warning("MetaVision.track_frames failed (%s); falling back to MockVision", e)
            return MockVision().track_frames(frames, prompts)


class MetaReports:
    name = "meta"

    def situation_report(self, summary: dict, lang: str) -> str:
        lang = "fil" if lang == "fil" else "en"
        try:
            client = get_client()
            if lang == "fil":
                developer = (
                    "Ikaw ay tagasulat ng bulletin para sa BDRRMO. "
                    "Sumulat ng maikli, malinaw na ulat sa lagay ng baha sa Filipino "
                    "mula sa JSON ng buod ng kalye. Isama ang lalim, passability, "
                    "takbo (tumataas/bumababa), at tao sa panganib kung mayroon. "
                    "Huwag banggitin ang SIMULATED, MOCK, o AI. Plain text lang."
                )
            else:
                developer = (
                    "You write BDRRMO flood situation bulletins. "
                    "Write a short, clear English bulletin from the street summary JSON. "
                    "Include depth, passability, trend (rising/falling), and people at risk if any. "
                    "Do not mention SIMULATED, MOCK, or AI. Plain text only."
                )
            text = _muse_chat(
                client,
                [
                    {"role": "developer", "content": developer},
                    {
                        "role": "user",
                        "content": json.dumps(summary, ensure_ascii=False, default=str),
                    },
                ],
            )
            if not text:
                raise RuntimeError("empty Muse sitrep")
            return text
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("Muse Spark sitrep", e)
            return MockReports().situation_report(summary, lang)


    def answer(self, summary: dict, question: str, lang: str) -> dict:
        """Muse Spark phrases the answer, grounded on the deterministic facts."""
        lang = "fil" if lang == "fil" else "en"
        facts = qa.answer(summary, question, lang)
        try:
            client = get_client()
            developer = (
                "You answer flood responders' questions for a BDRRMO. Use ONLY the street summary JSON "
                "and the grounded draft answer. Never invent streets, depths or people. Keep it to 2-3 short "
                "sentences, plain text, in " + ("Filipino" if lang == "fil" else "English") + ". "
                "End by reminding them to confirm on the ground. Do not mention SIMULATED, MOCK, or AI."
            )
            text = _muse_chat(client, [
                {"role": "developer", "content": developer},
                {"role": "user", "content": json.dumps({"question": question, "summary": summary,
                                                         "grounded_draft": facts["answer"]}, ensure_ascii=False, default=str)},
            ])
            if not text:
                raise RuntimeError("empty Muse answer")
            return {**facts, "answer": text, "provider": self.name}
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("Muse Spark answer", e)
            return {**facts, "provider": "mock"}


    def extract(self, note: str, est: dict) -> dict:
        """Muse Spark reads a Filipino/English/Taglish note into fixed fields. Rules in app/assess.py run after."""
        from .. import assess
        if not (note or "").strip():
            return {**assess.extract_text(note), "source": "none"}
        try:
            client = get_client()
            developer = (
                "You extract flood-report facts for barangay responders. The note may be Filipino, English or Taglish. "
                "Reply with ONLY compact JSON: {\"hazards\": [subset of " + json.dumps(list(assess.HAZARDS)) + "], "
                "\"people_at_risk\": true|false, \"water_level\": \"none\"|\"ankle\"|\"knee\"|\"waist\"|\"higher\"|null, "
                "\"rising\": \"yes\"|\"no\"|null, \"summary_en\": \"<=15 words\", \"confidence\": 0..1}. "
                "Only report what the note states; use null when not stated. Never invent a location."
            )
            raw = _muse_chat(client, [{"role": "developer", "content": developer},
                                      {"role": "user", "content": json.dumps({"note": note, "photo_estimate": {k: est.get(k) for k in ("band", "depth_cm", "reference")}}, ensure_ascii=False)}])
            return {**assess.clean_extraction(_parse_json_object(raw)), "source": "meta"}
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("Muse Spark extract", e)
            return {**assess.extract_text(note), "source": "mock-fallback"}

    def advisory(self, facts: dict) -> dict:
        from .. import assess
        base = assess.advisory_template(facts)
        try:
            client = get_client()
            developer = (
                "You are a calm, caring barangay disaster officer writing a short flood advisory for residents. "
                "Use ONLY the facts JSON: never invent streets, places, depths, times, counts, phone numbers or orders. "
                "Write natural, plain language a worried neighbour understands. Do NOT copy the app's status labels or "
                "field names verbatim (e.g. 'Help may be needed', 'Avoid this area', 'Needs confirmation', 'Use caution', "
                "'action_label'); say what they mean instead, e.g. 'please stay away from Rizal Street for now', "
                "'some residents there may need help and responders are checking', 'this report is not yet confirmed'. "
                "Lead with what people should do, mention the streets by name together with their barangay and city "
                "(use the 'place' field, e.g. 'M. H. del Pilar St in Malanday, Marikina City'), because the same street "
                "name exists in other cities, keep a steady reassuring tone, no "
                "ALL CAPS or alarmist words. Mention once that this is based on community reports and to follow "
                "official BDRRMO/PAGASA instructions. Reply ONLY JSON {\"en\": \"3-5 sentences\", "
                "\"fil\": \"the same advice in natural conversational Filipino (not word-for-word)\", "
                "\"sms\": \"one plain Taglish text message, at most 160 characters, naming the barangay and the key "
                "street(s) to avoid\"}."
            )
            raw = _muse_chat(client, [{"role": "developer", "content": developer},
                                      {"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=str)}])
            j = _parse_json_object(raw)
            en, fil, sms = str(j.get("en") or "").strip(), str(j.get("fil") or "").strip(), str(j.get("sms") or "").strip()
            if not en or not fil:
                raise ValueError("incomplete advisory")
            if not sms or len(sms) > 160:
                sms = base["sms"]
            return {"en": en, "fil": fil, "sms": sms, "provider": "meta"}
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("Muse Spark advisory", e)
            return {**base, "provider": "mock-fallback"}


class MetaAgent:
    name = "meta"

    def run(self, report: dict, tools) -> dict:
        try:
            return self._run_muse(report, tools)
        except Exception as e:
            if not _fallback_enabled():
                raise
            _note_fallback("Muse Spark triage", e)
            return {**MockAgent().run(report, tools), "source": "mock-fallback"}

    def _run_muse(self, report: dict, tools) -> dict:
        client = get_client()
        slim = {
            k: report.get(k)
            for k in (
                "id",
                "barangay",
                "street",
                "note",
                "band",
                "depth_cm",
                "reason",
                "lang",
                "lat",
                "lng",
                "status",
            )
        }
        developer = (
            "You are a flood-report triage planner for BDRRMO. "
            "Reply with ONLY compact JSON (no markdown): "
            '{"radius_m": <50-200>, "run_merge": true|false, '
            '"run_risk": true|false, "run_followup": true|false}. '
            "Set run_followup true only when band is cant_tell. "
            "Default radius_m 100; run_merge and run_risk true."
        )
        raw = _muse_chat(
            client,
            [
                {"role": "developer", "content": developer},
                {"role": "user", "content": json.dumps(slim, ensure_ascii=False, default=str)},
            ],
        )
        plan = _parse_json_object(raw)
        radius = int(plan.get("radius_m") or 100)
        radius = max(50, min(200, radius))
        run_merge = bool(plan.get("run_merge", True))
        run_risk = bool(plan.get("run_risk", True))
        run_followup = bool(plan.get("run_followup", report.get("band") == "cant_tell"))

        trace = []
        nearby = tools.get_nearby_reports(report, radius_m=radius)
        trace.append(("get_nearby_reports", len(nearby)))
        dup = tools.merge_duplicates(report, nearby) if run_merge else None
        trace.append(("merge_duplicates", dup))
        risk = tools.flag_people_at_risk(report) if run_risk else False
        trace.append(("flag_people_at_risk", risk))
        q = tools.ask_followup(report) if run_followup else None
        trace.append(("ask_followup", q))
        return {"duplicate_of": dup, "people_at_risk": risk, "followup": q, "trace": trace, "source": "meta"}


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in Muse reply: {text[:120]!r}")
    return json.loads(text[start : end + 1])
