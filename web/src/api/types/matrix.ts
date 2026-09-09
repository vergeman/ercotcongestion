// =============================================================================
// /matrix/frame — one bounded, day-stable constraint × settlement-point frame.
// The API owns the row and column ordering.  `sf.values` is row-major and is
// aligned exactly to `rows` then `columns`; it contains recovered implied shift
// factors, not an official ERCOT shift-factor field.
// =============================================================================

export type MatrixDamStatus = "pending" | "partial" | "available";

// Which axis the backend gave the primary ranked/searched list. The wire shape
// is unchanged (`rows` are always constraints, `columns` always settlement
// points); the client transposes `nodes` at draw time.
export type MatrixOrientation = "constraints" | "nodes";

export interface MatrixRow {
  constraint_key: string;
  constraint_name: string;
  contingency_name: string | null;
  constraint_type: string | null;
  forecast_mu: number;
  ercot_dam_mu: number | null;
  daily_rank: number;
  binding_hours: number;
  max_abs_sf: number;
}

export interface MatrixColumn {
  settlement_point: string;
  settlement_point_type: string | null;
  load_zone: string | null;
  max_abs_sf: number;
}

// A cell whose |value| reaches the frame's `sf_abs_cap` was pinned there by the
// ridge fit's clip — a bound, not a measurement. No parallel mask is sent: the
// clip is exact, so `Math.abs(v) >= sf_abs_cap` is the same test the server
// would apply, at a fraction of the payload.
export interface MatrixSfValues {
  row_count: number;
  column_count: number;
  values: number[];
}

export interface MatrixFrame {
  available: boolean;
  unavailable_reason: string | null;
  run_id: string;
  delivery_date: string;
  interval_ts: string;
  fit_window_start: string | null;
  fit_window_end: string | null;
  orientation: MatrixOrientation;
  dam_status: MatrixDamStatus;
  row_ordering: string;
  column_ordering: string;
  rows_truncated: boolean;
  columns_truncated: boolean;
  total_constraint_count: number;
  total_settlement_point_count: number;
  sf_day_max_abs: number;
  contribution_day_max_abs: number;
  // The fit's |SF| clip, so the threshold has one source rather than a
  // hardcoded 1.0 on both sides of the wire.
  sf_abs_cap: number;
  rows: MatrixRow[];
  columns: MatrixColumn[];
  sf: MatrixSfValues;
}

// Compact realized-range wire format. `sp_ids` is the one settlement-point
// index for the response; each entry's same-length arrays align to it.
export interface ErcotRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  congestion: Array<number | null>;
  spp: Array<number | null>;
}

export interface ErcotRangeResponse {
  start: string;
  end: string;
  count: number;
  sp_ids: string[];
  entries: ErcotRangeEntry[];
}
