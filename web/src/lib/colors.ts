// Fragility color scale

// TODO: revisit calibration once we have a wider data sample. Current
// thresholds are guesses from a slice of synthetic data — top observed value was
// ~30, noise floor ~1e-10.

// Approach: log scale, fixed absolute anchors. Stable across timesteps
// and queries — "red" means the same thing in March as it does in July.

const FRAGILITY_FLOOR = 1e-6; // below this → green (noise / no signal)
const FRAGILITY_RED = 100; // saturates at this value

export const FRAGILITY_ANCHORS = {
  floor: FRAGILITY_FLOOR,
  red: FRAGILITY_RED,
  // Decade tick marks for legend (log scale)
  ticks: [1e-6, 1e-4, 1e-2, 1, 100],
};

// Fragility: 0 → green, 0.5 → yellow, 1 → red
export function fragilityColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));

  let r: number, g: number, b: number;
  if (t < 0.5) {
    const s = t * 2;
    r = Math.round(34 + (234 - 34) * s);
    g = Math.round(197 + (179 - 197) * s);
    b = Math.round(94 + (8 - 94) * s);
  } else {
    const s = (t - 0.5) * 2;
    r = Math.round(234 + (220 - 234) * s);
    g = Math.round(179 + (38 - 179) * s);
    b = Math.round(8 + (38 - 8) * s);
  }
  return `rgb(${r},${g},${b})`;
}

// Map raw fragility values → [0, 1] using a fixed log scale.
// Values below FRAGILITY_FLOOR clamp to 0 (green).
// Values above FRAGILITY_RED clamp to 1 (red).
export function normalizeFragility(
  buses: Array<{ bus_id: string; fragility: number | null }>
): Map<string, number> {
  const logFloor = Math.log10(FRAGILITY_FLOOR);
  const logRed = Math.log10(FRAGILITY_RED);
  const logRange = logRed - logFloor;

  const map = new Map<string, number>();
  for (const b of buses) {
    const v = b.fragility ?? 0;
    if (v <= FRAGILITY_FLOOR) {
      map.set(b.bus_id, 0);
    } else {
      const norm = (Math.log10(v) - logFloor) / logRange;
      map.set(b.bus_id, Math.min(1, Math.max(0, norm)));
    }
  }
  return map;
}

// LMP color anchors ($/MWh) — fixed-scale fallback
//   - negative: oversupply (rare but informative; renewables curtailment)
//   - mid: nominal market clearing
//   - high: scarcity / congestion
const LMP_LOW = -50; // deeply negative → blue
const LMP_MID = 30; // normal market → neutral/cream
const LMP_HIGH = 500; // scarcity territory → orange/red

export function normalizeLmp(value: number | null): number {
  if (value == null) return 0.5;
  if (value <= LMP_MID) {
    // LOW → MID maps to 0 → 0.5
    const t = (value - LMP_LOW) / (LMP_MID - LMP_LOW);
    return Math.max(0, Math.min(0.5, t * 0.5));
  } else {
    // MID → HIGH maps to 0.5 → 1.0, log-scaled for the long tail
    const logMid = Math.log10(LMP_MID);
    const logHi = Math.log10(LMP_HIGH);
    const logV = Math.log10(Math.min(LMP_HIGH, value));
    return 0.5 + ((logV - logMid) / (logHi - logMid)) * 0.5;
  }
}

// Per-snapshot adaptive LMP scaling.
// Anchored at zero (cream) so blue/orange retain their absolute meaning
// (negative = oversupply, positive = scarcity). The dynamic range stretches
// to the snapshot's own extremes — quiet hours don't wash out, busy hours
// don't saturate everything red.
export interface LmpDomain {
  min: number;
  max: number;
  // Span used below zero (always positive). 0 if no negative LMPs.
  negSpan: number;
  // Span used above zero (always positive). 0 if no positive LMPs.
  posSpan: number;
}

export function computeLmpDomain(
  buses: Array<{ lmp: number | null }>
): LmpDomain {
  let min = Infinity;
  let max = -Infinity;
  for (const b of buses) {
    if (b.lmp == null) continue;
    if (b.lmp < min) min = b.lmp;
    if (b.lmp > max) max = b.lmp;
  }
  if (!isFinite(min) || !isFinite(max)) {
    return { min: 0, max: 0, negSpan: 0, posSpan: 0 };
  }
  return {
    min,
    max,
    negSpan: min < 0 ? -min : 0,
    posSpan: max > 0 ? max : 0,
  };
}

export function normalizeLmpAdaptive(
  value: number | null,
  domain: LmpDomain
): number {
  if (value == null) return 0.5;
  if (value === 0) return 0.5;
  if (value < 0) {
    if (domain.negSpan === 0) return 0.5;
    // -negSpan → 0 maps to 0 → 0.5
    const t = 1 - Math.min(1, -value / domain.negSpan);
    return 0.5 * t;
  } else {
    if (domain.posSpan === 0) return 0.5;
    // 0 → posSpan maps to 0.5 → 1, log-compressed so a single outlier
    // doesn't crush the rest of the distribution against cream.
    const logMax = Math.log10(1 + domain.posSpan);
    const logV = Math.log10(1 + Math.min(value, domain.posSpan));
    return 0.5 + 0.5 * (logV / logMax);
  }
}

// LMP: blue (low) → white → orange (high), per-snapshot normalized
export function lmpColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));
  if (t < 0.5) {
    const s = t * 2;
    const r = Math.round(59 + (226 - 59) * s);
    const g = Math.round(130 + (232 - 130) * s);
    const b = Math.round(246 + (200 - 246) * s);
    return `rgb(${r},${g},${b})`;
  } else {
    const s = (t - 0.5) * 2;
    const r = Math.round(226 + (249 - 226) * s);
    const g = Math.round(232 + (115 - 232) * s);
    const b = Math.round(200 + (22 - 200) * s);
    return `rgb(${r},${g},${b})`;
  }
}
