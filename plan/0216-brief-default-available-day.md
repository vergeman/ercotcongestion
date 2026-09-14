# 0216 - Brief default available day

Type: fix
Branch: fix/0216-brief-default-available-day

## Goal

* Default a root Brief visit to today’s DAM view when it is available.
* Fall back to the newest published Brief day when forecast publication is behind.

## Context

* The prior root default used the newest artifact, often opening a T+1/T+2 forecast.
* A fixed current-date default can open an empty Brief when no current-day artifact was published.

## Approach

* Work in: `web/src/features/brief/useBriefDay.ts`.
* On a root visit with no shared cursor date, request the lightweight latest-hero metadata.
* Set the default delivery date to `min(today in CT, latest available delivery date)`; retain the empty state if no artifact exists.
* Keep an explicit URL cursor date authoritative, and leave the existing adjacent-day controls unchanged.

## Acceptance

* [x] A normal root visit opens today when a T+1/T+2 artifact is available.
* [x] If the latest available artifact predates today, the Brief opens that date instead of an empty current day.
* [x] A shared cursor date and forward forecast navigation continue to work.
* [x] `docker compose run --rm --no-deps web npm run build` passes.
