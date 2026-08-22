import { addDays, format } from "date-fns";
import { buildMapLink } from "../../lib/mapLinks";
import { ctInputToUtc } from "../../lib/time";
import type { BriefHero } from "../../api/types";

export function briefDayBounds(day: string) {
  const nextDay = format(
    addDays(new Date(`${day}T12:00:00Z`), 1),
    "yyyy-MM-dd"
  );
  return {
    start: ctInputToUtc(`${day}T00:00`),
    end: ctInputToUtc(`${nextDay}T00:00`),
  };
}

export function briefMapWatchHref(hero: BriefHero | null, settled: boolean) {
  if (!hero?.cursor) return null;
  return buildMapLink({
    t: new Date(hero.cursor.ws),
    ws: new Date(hero.cursor.ws),
    we: new Date(hero.cursor.we),
    view: settled ? "market" : "forecast",
    data: "lmp",
    autoPlay: true,
  });
}
