import type { ViewMode } from "../api/types";

/**
 * Curated demo events. Each entry defines a time window worth loading,
 * a "cursor" timestamp the slider should land on after load, and an
 * optional preferred view mode for the moment.
 *
 * All timestamps are ISO 8601 in UTC. The ingestion pipeline stores
 * `interval_ts` as UTC and the prefetch layer parses these as Date
 * objects, so UTC strings keep us off DST seams.
 *
 * Sized so the playback scrubber has enough texture around the cursor:
 * windows are ~12-24h wide centered on the moment of interest.
 */
export interface CuratedEvent {
  id: string;
  label: string;
  description: string;
  what_it_tests: string;
  window_start: string;
  window_end: string;
  cursor_ts: string;
  suggested_view?: ViewMode;
}

export const CURATED_EVENTS: CuratedEvent[] = [
  {
    id: "baseline_2005_apr16",
    label: "Quiet baseline",
    description:
      "Apr 16, 2005 — mild spring afternoon. Low load, no congestion, no scarcity.",
    what_it_tests:
      "Anchor for 'nothing happening looks like nothing.' Confirms the map reads cleanly when the grid is unstressed.",
    window_start: "2005-04-16T06:00:00Z",
    window_end: "2005-04-17T06:00:00Z",
    cursor_ts: "2005-04-16T20:00:00Z",
    suggested_view: "modeled_congestion",
  },
  {
    id: "wind_oversupply_2005_jan05",
    label: "Wind oversupply",
    description:
      "Jan 5, 2005 — overnight West Texas wind ramp pushing into negative LMPs.",
    what_it_tests:
      "Negative-pricing spatial pattern. Where does the surplus get stuck, and does the modeled congestion light up the export-constrained corridors?",
    window_start: "2005-01-05T00:00:00Z",
    window_end: "2005-01-06T00:00:00Z",
    cursor_ts: "2005-01-05T08:00:00Z",
    suggested_view: "lmp",
  },
  {
    id: "winter_scarcity_2005_jan08",
    label: "Winter scarcity",
    description:
      "Jan 8, 2005 — cold morning peak. Hub prices spike, system-wide stress.",
    what_it_tests:
      "Modeled-congestion-vs-hub-price coupling. Is the model's stress signal aligned with where the market is paying the most?",
    window_start: "2005-01-08T00:00:00Z",
    window_end: "2005-01-09T00:00:00Z",
    cursor_ts: "2005-01-08T13:00:00Z",
    suggested_view: "modeled_congestion",
  },
  {
    id: "rabbit_hill_2005_feb19",
    label: "Rabbit Hill",
    description:
      "Feb 19, 2005 — localized line stress at the Rabbit Hill corridor.",
    what_it_tests:
      "Highest-signal localized stress test. Rank-difference view should agree with reality here if the model is doing anything useful.",
    window_start: "2005-02-19T00:00:00Z",
    window_end: "2005-02-20T00:00:00Z",
    cursor_ts: "2005-02-19T15:00:00Z",
    suggested_view: "congestion_vs_basis",
  },
  {
    id: "summer_stability_2005_may23",
    label: "Summer heat (negative result)",
    description:
      "May 23, 2005 — hot afternoon, heavy load, but no DC-OPF binding.",
    what_it_tests:
      "Deliberate negative result: voltage / transient stability constraints (VSAT/TSAT) drive real basis here, and a DC model can't see them. Honest about the limits.",
    window_start: "2005-05-23T12:00:00Z",
    window_end: "2005-05-24T06:00:00Z",
    cursor_ts: "2005-05-23T21:00:00Z",
    suggested_view: "congestion_vs_basis",
  },
];

export const DEFAULT_EVENT_ID = "baseline_2005_apr16";
