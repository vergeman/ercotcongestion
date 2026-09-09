// Scoreboard date labels. Both format in UTC — the scoreboard's weeks and
// delivery days are UTC-anchored, unlike the Brief's CT day. Keep the zone here;
// do not fold these into the shared lib/format date helpers.

export const fmtWeek = (w: string): string =>
  new Date(`${w}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

export const fmtDay = (d: string): string =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
