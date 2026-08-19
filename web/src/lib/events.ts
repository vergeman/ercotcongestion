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
      "Feb 19-21, 2025: Austin suburb saturates during the winter morning peak. Rabbit Hill prices to +$5,977/MWh at 6am. Collapses to +$242 by noon, then does it again the next morning at a fifth the size.",
    what_it_tests:
      "A single, localized congestion: radial overload produces the widest node spread of the year. The constraint peaked at $7,577 on the 20th but only $323 on the 19th",
    window_start: "2025-02-19T18:00:00Z",
    window_end: "2025-02-21T18:00:00Z",
    cursor_ts: "2025-02-20T12:00:00Z",
    suggested_view: "congestion",
  },
  {
    id: "farwest_diurnal_2025_jun20",
    label: "Far West Sign Flip",
    description:
      "Jun 20-21, 2025: Permian congestion flips sign twice a day: +$34/MWh overnight when the region imports across saturated 138 kV paths, then -$24/MWh at midday when 5.6 GW of local solar saturates the  export paths instead.",
    what_it_tests:
      "Not just the sign flip but the footprint behind it: flat slab at midday, gradient at night. Matching one and not the other pins which constraints the model misses.",
    window_start: "2025-06-20T05:00:00Z",
    window_end: "2025-06-22T05:00:00Z",
    cursor_ts: "2025-06-21T00:00:00Z",
    suggested_view: "congestion",
  },

  {
    id: "winter_storm_fern_2026_jan24",
    label: "Winter Storm Fern",
    description:
      "Jan 24, 2026 - Jan 26, 2026: winter storm Fern: widest congestion $1,618/Mwh across nodes, peak system lambda at $1,915. The  Rio Grande Valley wind is bottled up at -$1,454, significant congestion in San Antonio on the 25th, and PALACIOS_RN at $20,941 at 0600",
    what_it_tests:
      "Both Scarcity and congestion from system wide weather event",
    window_start: "2026-01-24T06:00:00Z",
    window_end: "2026-01-27T06:00:00Z",
    cursor_ts: "2026-01-26T12:00:00Z",
    suggested_view: "congestion",
  },

  {
    id: "pure_congestion_2026_apr26",
    label: "Congestion without scarcity",
    description:
      "Apr 27, 2026, 12:00 CST: system lambda is $7.53/MWh; the map is almost pure transmission congestion. Houston industrial prices to +$89 while Panhandle sits at -$15. Cheaper West and East solar can't reach the coastal load pocket. ~8hours later solar collapses, system lambda hits $490, and the map inverts: coast becomes the cheapest price at -$123.",
    what_it_tests:
      "Three footprints, one map: a flat Far West, a sharp gradient into Houston, and a north-west Dallas cluster that looks regional but results from three unrelated constraints. ",
    window_start: "2026-04-26T05:00:00Z",
    window_end: "2026-04-28T05:00:00Z",
    cursor_ts: "2026-04-27T17:00:00Z",
    suggested_view: "congestion",
  },
];

export const DEFAULT_EVENT_ID = "baseline_2025_apr16";
