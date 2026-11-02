# Report-understanding eval (Muse Spark)

**Data:** `sample_data/eval/reports_synthetic.json`, 26 **synthetic** Filipino / English / Taglish text reports written and labeled by the team. Prototype eval only: not real reports, not field accuracy, and labels share the authors' bias.

| Metric | Result |
|---|---|
| Water level extracted correctly | 92% |
| People-at-risk flag correct | 88% |
| Hazard precision / recall | 94% / 94% |
| Severity agreement with team label | 92% |
| Critical cases caught (recall) | 100% |
| Duplicate grouping, pairwise accuracy | 100% (precision 100%, recall 92%) |
| Avg extraction time per report | 5688 ms |

Severity = deterministic rules in `app/assess.py` applied to the extracted fields. Grouping = `assess.group` (same barangay + street or within 60 m, within 90 min).

| ID | Note | Level (label → got) | Hazards got | Severity (label → got) |
|---|---|---|---|---|
| T01 | Hanggang tuhod na ang baha dito sa Bayabas | knee → knee | – | moderate → moderate |
| T02 | Knee deep na rin dito malapit sa chapel, tumataas pa | knee → knee | – | moderate → moderate |
| T03 | Bewang na! May matanda sa second floor hindi makalabas | waist → waist | stranded_person, vulnerable_person | critical → critical |
| T04 | Waist-deep, may live wire na nakalaylay sa tubig | waist → waist | live_wire | critical → critical |
| T05 | Delikado, may kuryente sa poste malapit sa baha | None → None | live_wire | moderate → critical ✗ |
| T06 | Ankle deep lang, passable pa ang tricycle | ankle → ankle | – | low → low |
| T07 | Baha na dito! Ang lalim | None → None | – | unknown → unknown |
| T08 | Humupa na, tuyo na ang kalsada | none → none | – | low → low |
| T09 | Cars stalled, water up to the knee | knee → knee | vehicles_stuck | moderate → moderate |
| T10 | Bumababa na ang tubig, hanggang tuhod pa rin | knee → knee | – | moderate → moderate |
| T11 | Saklolo! Nasa bubong kami ng mga bata | higher → None ✗ | stranded_person, vulnerable_person | critical → critical |
| T12 | Family trapped on the roof, kids with them, need rescue | higher → None ✗ | stranded_person, vulnerable_person | critical → critical |
| T13 | Gutter level lang, okay pa | ankle → ankle | – | low → low |
| T14 | Water everywhere, photo from window | None → None | – | unknown → unknown |
| T15 | Malakas ang agos dito, hanggang baywang | waist → waist | strong_current | critical → critical |
| T16 | Mataas pa rin, hanggang baywang | waist → waist | – | high → high |
| T17 | Same level, waist deep still | waist → waist | – | high → high |
| T18 | Dry for now | none → none | – | low → low |
| T19 | May buntis dito na kailangan ilikas, hanggang tuhod na | knee → knee | stranded_person, vulnerable_person | critical → critical |
| T20 | Hindi makadaan ang jeep, lagpas tuhod | knee → knee | vehicles_stuck | moderate → moderate |
| T21 | Curb barely covered | ankle → ankle | – | low → low |
| T22 | Lumalalim na, ankle pa lang pero mabilis | ankle → ankle | rising_fast | low → moderate ✗ |
| T23 | Lolo naming naka-wheelchair, hindi kami makalabas, baha na sa sala | None → None | stranded_person, vulnerable_person | critical → critical |
| T24 | Chest deep na, rumaragasa ang tubig | higher → higher | strong_current | critical → critical |
| T25 | No flood here, clear na | none → none | – | low → low |
| T26 | Nakuryente daw yung aso, may kable sa tubig, tuhod ang baha | knee → knee | live_wire | critical → critical |
