# Analysis

Query-backed analysis primitives used to build the daily Brief, classify and
render its hero copy, and grade settled forecasts. Database reads and assembly
stay separate from the pure projection, classification, and scoring helpers.

## Shared metadata

| File | Description |
| --- | --- |
| `metadata.py` | Loads settlement-point metadata and derives hub/load-zone types from names when static metadata is absent. |

## Daily Brief hero

| File | Description |
| --- | --- |
| `hero.py` | Pure classifier for the daily Brief hero. Turns window summaries into magnitude, regime, location, exception, and verdict slots. |
| `hero_builder.py` | Coordinates artifact and compact database-window reads to assemble classifier-ready hero slots and conditions for a delivery day. |
| `hero_window.py` | Provides as-of, trailing-window database readers and summaries for constraints, nodes, geography, and load conditions. |
| `phrases.py` | The hero phrase book. Maps classified slots to controlled copy segments and renders the final structured hero text. |

## Brief grades

| File | Description |
| --- | --- |
| `grade.py` | Pure per-delivery-day grading calculations. Aligns profiles and derives detection, magnitude, timing, calibration, and baseline metrics. |
| `brief_grade.py` | Loads forecast and settled constraint/node profiles, constructs comparison baselines, and serializes neutral Brief-grade payloads. |
