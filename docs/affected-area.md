# How BahaBantay draws the affected area

A barangay is a label, not a flood footprint. Each report is snapped to a ~250 m grid square and only squares with recent reports are colored (`/api/cells`).

- **Time decay:** a report's weight is `exp(-ln2 · age / 60 min)` (half-life `BAHABANTAY_HALF_LIFE_MIN`, default 60). Reports older than `BAHABANTAY_EXPIRE_H` (default 6 h) are ignored by the map and the incident list.
- **Dedupe:** reports from the same browser (anonymous random id, stored hashed) in the same square count as one independent reporter. Incident corroboration uses the same rule.
- **Confidence:** `1 − Π(1 − sᵢ)` over independent reporters, where `sᵢ = weight × evidence quality (photo AI > reporter's tap > note only) × location accuracy (GPS 1.0, map pin 0.8, barangay center 0.3)`. "Still flooded" votes raise it; a responder confirm sets it to at least 0.9.
- **States:** *Observed & confirmed* (solid): newest report ≤ 90 min, confidence ≥ 0.5 and ≥ 2 independent reporters / a community vote / responder confirm. *Unconfirmed* (dashed): recent but single reporter. *Old or weak* (gray). No square = no data, never "not flooded".
- **Privacy:** the public map and API show only the square; responders (`view=responder`) also get the exact points.
- **Demo clock:** sample reports are re-timed relative to now on start and every 30 min (`BAHABANTAY_DEMO_CLOCK=1`), so the demo always looks live.

## Extra report fields

- **Depth in cm** (optional, 0–300): used for the level when the photo gives no confident estimate and the reporter did not tap a level (ankle < 25, knee < 60, waist < 110, else higher). Confidence 0.65; feeds the cell's weighted depth.
- **Water trend** (rising / steady / going down / not sure): replaces the old yes/no "rising" question; the newest answer within 90 min wins, so a "going down" report cancels an older "rising". The legacy `rising` field is still accepted and kept in sync.
- **Can a car pass?** (yes / no / not sure): a recent "no" turns the label into "Avoid this area" (needs verification until a responder confirms) and is shown on the cell.
