// ERCOT SP snapshot payload. `sp_id` is the ERCOT settlement point
// identifier; `congestion` is the reference-adjusted congestion value
// (SPP − system_λ) from the run's congestion matrix.
export interface ErcotSpState {
  sp_id: string;
  congestion: number | null;
}

export interface ErcotStateRangeEntry {
  interval_ts: string;
  sps: ErcotSpState[];
}

export interface ErcotStateRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ErcotStateRangeEntry[];
}

// Raw DAM SPP per settlement point, per hour. Feeds the LMP palette so the
// price view renders directly from ERCOT's published prices.
export interface ErcotSpSpp {
  sp_id: string;
  spp: number | null;
}

export interface ErcotSppRangeEntry {
  interval_ts: string;
  sps: ErcotSpSpp[];
}

export interface ErcotSppRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ErcotSppRangeEntry[];
}

// The palette drives both panes (prediction left, actual ERCOT right). Each
// mode picks the ERCOT quantity both panes render:
//   congestion → SPP − system_λ  (diverging palette)
//   lmp        → raw DAM SPP      (LMP palette)
export type ViewMode = "congestion" | "lmp";

// Per-SP row for the current hour, merged from the congestion and SPP caches.
// `sp_id` matches the topology feature's promoteId so the map can key
// feature-state directly off it.
export interface SpRow {
  sp_id: string;
  congestion: number | null;
  spp: number | null;
}

// ERCOT settlement point features in /topology.settlement_points.
export interface SPFeatureProperties {
  sp_id: string;
  sp_type: string;
  load_zone: string | null;
  capacity_mw: number;
}
