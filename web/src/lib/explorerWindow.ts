export const MAX_EXPLORER_WINDOW_HOURS = 14 * 24;

const MAX_EXPLORER_WINDOW_MS = MAX_EXPLORER_WINDOW_HOURS * 60 * 60 * 1000;

export function validateExplorerWindow(start: Date, end: Date): string | null {
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "Choose valid start and end dates.";
  }
  if (start.getTime() > end.getTime()) {
    return "End must be at or after the start.";
  }
  if (end.getTime() - start.getTime() > MAX_EXPLORER_WINDOW_MS) {
    return "Choose a range no longer than 14 days.";
  }
  return null;
}
