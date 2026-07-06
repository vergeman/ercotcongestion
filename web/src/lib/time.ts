import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

// ERCOT operates on Central. All user-facing timestamps in the UI are
// rendered in this zone; the API/wire format stays UTC.
export const ERCOT_TZ = "America/Chicago";

// Format a real moment as CT wall-clock. Handles DST.
export function formatCT(d: Date, fmt: string): string {
  return formatInTimeZone(d, ERCOT_TZ, fmt);
}

// Convert a naïve `<input type="datetime-local">` string (e.g.
// "2025-01-03T10:00") to the absolute UTC moment it represents when
// interpreted in Central time.
export function ctInputToUtc(local: string): Date {
  return fromZonedTime(local, ERCOT_TZ);
}

// Format a real moment as the "yyyy-MM-dd'T'HH:mm" string a
// `<input type="datetime-local">` accepts, using CT wall-clock.
export function utcToCTInputString(d: Date): string {
  return formatInTimeZone(d, ERCOT_TZ, "yyyy-MM-dd'T'HH:mm");
}
