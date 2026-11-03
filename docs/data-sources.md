# Data sources

## Barangay list and centroids (`app/geo/barangays.csv.gz`)

- **What:** all 42,010 barangays in the Philippines with PSGC code, name, city/municipality, province, region and an approximate centroid (lat/lng).
- **Built from:** the [`psgc`](https://pypi.org/project/psgc/) Python package v2026.4.13.0 ([github.com/fish-and-bear/psgc](https://github.com/fish-and-bear/psgc)), **MIT License**, community-maintained, not affiliated with PSA.
  - Names, codes and hierarchy: Philippine Statistics Authority (PSA) PSGC, Q1 2026 release.
  - Centroids: polygon centroids from the HDX/OCHA Philippines administrative boundaries (COD-AB, Nov 2023, sourced from PSA/NAMRIA), published on HDX under CC BY-IGO. 84 barangays have no polygon match; they are flagged `approx=1`.
- **Regenerate:** `pip install psgc==2026.4.13.0`, export `psgc.to_csv(level="barangay")`, keep columns code, name, city, province, region, lat, lng, approx (see `app/geo.py`).
- **How it is used:** the list stays on the server. The browser only gets up to 8–20 search hits (`/api/barangays/search?q=`) or the 3 nearest centroids (`/api/barangays/nearest`). A centroid is used only to label a barangay and to center the map; it is never shown as a flood location, and reports placed at a centroid are marked "approximate location".
- **Responder coverage:** the demo's responder coverage is Marikina City. Reports anywhere else are accepted and labeled "Outside responder coverage".
