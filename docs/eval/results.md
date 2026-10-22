# Depth estimator eval

**Data:** `sample_data/eval/labeled_simulated.json` — **SIMULATED** synthetic masks with known depths. These numbers only check the depth math and can't-tell logic. They are NOT real-world accuracy. Replace with real flood photos with tape-measured depths before quoting any figure.

- Items: 25
- Mean absolute error (excluding can't tell): **5.3 cm**
- Level accuracy (excluding can't tell): **71%**
- Can't tell rate: **16%** (4 of 25)

| Level | Items | Correct |
|---|---|---|
| none | 1 | 0 |
| ankle | 6 | 6 |
| knee | 4 | 2 |
| waist | 10 | 7 |
| chest | 0 | 0 |

| ID | Ref | True cm | Est cm | Est level | Note |
|---|---|---|---|---|---|
| SIM-01 | person | 96 | 90 | waist |  |
| SIM-02 | door | 102 | 101 | waist |  |
| SIM-03 | car_tire | 27 | 25 | knee |  |
| SIM-04 | jeepney | 30 | 29 | knee |  |
| SIM-05 | curb | 3 | 4 | ankle |  |
| SIM-06 | person | 105 | 113 | chest |  |
| SIM-07 | door | 144 | – | cant_tell | no_reference |
| SIM-08 | car_tire | 55 | 54 | knee |  |
| SIM-09 | jeepney | 109 | 135 | chest |  |
| SIM-10 | curb | 12 | 12 | ankle |  |
| SIM-11 | person | 87 | 88 | waist |  |
| SIM-12 | door | 12 | – | cant_tell | low_confidence |
| SIM-13 | car_tire | 7 | 8 | ankle |  |
| SIM-14 | jeepney | 31 | 17 | ankle |  |
| SIM-15 | curb | 10 | 10 | ankle |  |
| SIM-16 | person | 57 | 60 | waist |  |
| SIM-17 | door | 84 | 92 | waist |  |
| SIM-18 | car_tire | 2 | 8 | ankle |  |
| SIM-19 | jeepney | 32 | 13 | ankle |  |
| SIM-20 | curb | 6 | – | cant_tell | no_reference |
| SIM-21 | person | 69 | 70 | waist |  |
| SIM-22 | door | 88 | 80 | waist |  |
| SIM-23 | car_tire | 14 | 10 | ankle |  |
| SIM-24 | jeepney | 16 | – | cant_tell | low_confidence |
| SIM-25 | curb | 12 | 12 | ankle |  |
