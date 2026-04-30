// Fragility: 0 → green, 0.5 → yellow, 1 → red
// Input: normalized 0–1
export function fragilityColor(norm: number): string {
  // Clamp
  const t = Math.max(0, Math.min(1, norm));

  let r: number, g: number, b: number;
  if (t < 0.5) {
    // green → yellow
    const s = t * 2;
    r = Math.round(34 + (234 - 34) * s);
    g = Math.round(197 + (179 - 197) * s);
    b = Math.round(94 + (8 - 94) * s);
  } else {
    // yellow → red
    const s = (t - 0.5) * 2;
    r = Math.round(234 + (220 - 234) * s);
    g = Math.round(179 + (38 - 179) * s);
    b = Math.round(8 + (38 - 8) * s);
  }
  return `rgb(${r},${g},${b})`;
}

// Convert fragility array to normalized map
export function normalizeFragility(
  buses: Array<{ bus_id: string; fragility: number | null }>
): Map<string, number> {
  const vals = buses.map((b) => b.fragility ?? 0);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const map = new Map<string, number>();
  for (const b of buses) {
    map.set(b.bus_id, ((b.fragility ?? 0) - min) / range);
  }
  return map;
}

// LMP: blue (low) → white → orange (high)
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
