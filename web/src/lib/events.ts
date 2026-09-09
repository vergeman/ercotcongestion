import type { MapDataMode } from "../api/types";

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
  suggested_view?: MapDataMode;
}

export const CURATED_EVENTS: CuratedEvent[] = [
  /*
  {
    id: "wind_oversupply_2025_jan05",
    label: "Wind Oversupply",
    description:
      "Jan 4, 2025 - Jan 6, 2025: overnight West Texas wind ramp pushing into negative LMPs, then drop of wind with increased demand leads to system price spike",
    what_it_tests:
      "Exceptionally high wind, negative system pricing in Jan 4th evening, morning Jan 5th. then cold weather on Jan 6th evening pushed System prices upward over $70/MWh.",
    window_start: "2025-01-03T00:00:00Z",
    window_end: "2025-01-06T00:00:00Z",
    cursor_ts: "2025-01-04T08:00:00Z",
    suggested_view: "lmp",
  },

  {
    id: "winter_scarcity_2025_jan15",
    label: "Winter Scarcity",
    description:
      "Jan 22, 2025: record winter load ~78 GW morning peak, but relatively stable to low system pricing as high wind generation paired with far east solar generation coming online to mitigate congestion.",
    what_it_tests:
      "Solar placement easily mitigates increased load; not about total load but about geographic placement",
    window_start: "2025-01-15T00:00:00Z",
    window_end: "2025-01-16T00:00:00Z",
    cursor_ts: "2025-01-15T13:00:00Z",
    suggested_view: "congestion",
  },
*/
  {
    id: "rabbit_hill_2025_feb20",
    label: "Rabbit Hill",
    description:
      "Feb 19-21, 2025: winter-morning congestion near Austin sends Rabbit Hill to $5,977/MWh.",
    what_it_tests:
      "A localized radial overload with a wide nodal spread.",
    window_start: "2025-02-19T18:00:00Z",
    window_end: "2025-02-21T18:00:00Z",
    cursor_ts: "2025-02-20T12:00:00Z",
    suggested_view: "congestion",
  },
  {
    id: "farwest_diurnal_2025_jun20",
    label: "Far West Sign Flip",
    description:
      "Jun 20-21, 2025: Permian congestion flips from overnight imports to midday solar exports.",
    what_it_tests:
      "Different daytime and overnight constraint footprints.",
    window_start: "2025-06-20T05:00:00Z",
    window_end: "2025-06-22T05:00:00Z",
    cursor_ts: "2025-06-21T00:00:00Z",
    suggested_view: "congestion",
  },

  {
    id: "winter_storm_fern_2026_jan24",
    label: "Winter Storm Fern",
    description:
      "Jan 24-26, 2026: Winter Storm Fern brings scarcity and severe regional congestion.",
    what_it_tests:
      "Systemwide weather-driven scarcity and congestion.",
    window_start: "2026-01-24T06:00:00Z",
    window_end: "2026-01-27T06:00:00Z",
    cursor_ts: "2026-01-26T12:00:00Z",
    suggested_view: "congestion",
  },

  {
    id: "pure_congestion_2026_apr26",
    label: "Congestion without scarcity",
    description:
      "Apr 27, 2026: low system price masks strong transmission congestion from Houston to the Panhandle.",
    what_it_tests:
      "Three distinct regional constraint footprints.",
    window_start: "2026-04-26T05:00:00Z",
    window_end: "2026-04-28T05:00:00Z",
    cursor_ts: "2026-04-27T17:00:00Z",
    suggested_view: "congestion",
  },
];

export const DEFAULT_EVENT_ID = "baseline_2025_apr16";
