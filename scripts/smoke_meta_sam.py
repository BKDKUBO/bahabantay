"""Live SAM 3.1 smoke: segment one sample image for water + person. Prints labels/bboxes/scores only."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.providers.meta import MetaVision, load_dotenv  # noqa: E402


def main() -> int:
    load_dotenv()
    img_path = ROOT / "sample_data" / "images" / "sample_01.jpg"
    image = img_path.read_bytes()
    print(f"image={img_path.name} bytes={len(image)}")
    seg = MetaVision().segment(image, ["water", "person"])
    if not seg.masks:
        print("masks: (none)")
        return 0
    for m in seg.masks:
        print(f"label={m.label} bbox={tuple(round(x, 4) for x in m.bbox)} score={m.score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
