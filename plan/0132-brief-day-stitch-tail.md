# 0132 - brief-day-stitch-tail

Type: fix
Branch: fix/0132-brief-day-stitch-tail

## Goal

* Make forward-looking Brief days render as soon as their own artifact lands: t+1 (final)
  and t+2 (preview) must be available the afternoon their producing runs complete.
* Stop letting the missing next-UTC-day artifact veto an entire delivery day of data that
  is already in the database.
* Surface partial/mixed coverage honestly in the response instead of `artifact_missing`.

## Context

* Each `forecast_sf_artifact` blob covers one **UTC** day (00:00Z–23:00Z). The Brief
  displays **CT** delivery days (05Z→05Z), so `_forecast_mu_profile` /
  `_forecast_node_profile` (`api/analysis.py:360-390`) and `_daily_node_contributions`
  stitch artifacts for UTC dates D and D+1 — and require both **at the same horizon**,
  all-or-nothing.
* Day D at horizon 1 therefore cannot render until D+1's final exists — 17:00Z *on the
  delivery day itself*. Day D at horizon 2 needs D+1's preview, which lands a day after
  D's own preview. Net effect: the most forward day on each track never renders; every
  day becomes viewable one run-cycle late. Verified live 2026-08-14: 8/15 and 8/16 both
  `artifact_missing` while their artifacts sit in prod; `&horizon=2` renders 8/15 fully.
* Only the last ~5 CT-evening hours (00Z–04/05Z of D+1) come from the D+1 artifact. The
  stitch throws away 19 available hours over the 5 it lacks.
* **This is a stopgap.** `0133-ct-delivery-day-blocks` re-cuts the artifact block to the
  CT day, deletes the two-artifact stitch entirely, and with it everything this plan
  adds. Keep the change small and contained so that deletion is clean.

## Approach

* Work in: `api/analysis.py`, `api/services/sf_artifacts.py`, `api/models.py`,
  `web/src/pages/BriefPage.tsx`; tests in `api/tests/`.
* Entry point: `_forecast_mu_profile` and `_forecast_node_profile`; audit
  `_daily_node_contributions` for the same D+1 requirement.
* Make the D+1 artifact load degrade in two steps, keeping the D artifact at the
  resolved horizon mandatory:
  1. **Cross-horizon tail fallback**: load D+1 with `horizon=None` coalescing
     (`load_daily_artifact` already supports it) — an h1 day borrows its evening tail
     from the h2 preview when the h1 tail doesn't exist yet.
  2. **Truncation**: if D+1 has no artifact at any horizon (the t+2 preview case),
     build the profile from D alone — 19 of 24 CT hours, ending 6pm CT.
* Report coverage in the available-response models: add `tail_horizon: int | null`
  (set when the tail came from a different horizon than the day) and
  `hours_covered: int`. BriefPage shows a small provenance note when
  `hours_covered < 24` ("evening hours arrive with the next run") or when the tail is
  preview-vintage. Do not invent a second horizon badge system.
* **Grading endpoints stay strict**: `get_grade` / `get_grade_history` must not grade a
  19-hour forecast against a 24-hour settled day. If the full CT day is not covered
  (after the cross-horizon fallback), keep returning the existing unavailable shape.
  Display endpoints (`hero`, `top-constraints`, `standouts`, `top-nodes`, `context`)
  serve partial.
* Do NOT touch: `compute/` (block cut is 0133), `_resolve_horizon` day-level semantics,
  the artifact cache keying.

## Acceptance

* [x] With prod-shaped fixtures (D h1+h2, D+1 h2 only): delivery day D is available at
      horizon 1 with 24 hours and `tail_horizon: 2`.
* [x] With D h2 only and no D+1 artifact: day D is available, `hours_covered: 19`,
      profile ends at the last D-artifact hour inside the CT day.
* [x] `get_grade` for a day whose tail is missing at every horizon stays unavailable;
      fully-covered days grade byte-identically to before this change.
* [x] Live check after the 17:00Z and 20:15Z runs: both
      `/?t=<t+1>` and `/?t=<t+2>` Brief URLs render with no `artifact_missing` responses.
* [x] BriefPage shows the partial/mixed-tail provenance note only in those two states.
