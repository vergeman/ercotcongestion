import Tooltip from "../../ui/Tooltip";
import DateRangePicker from "../../playback/DateRangePicker";
import { CURATED_EVENTS } from "../../../lib/events";

const formatDay = (day: string) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "America/Chicago",
  });

interface Props {
  day: string | null;
  adjacentDays: { previous: string | null; next: string | null };
  loading: boolean;
  activeEventId: string | null;
  onSelectDay: (day: string) => void;
  onSelectEvent: (event: {
    id: string;
    cursor_ts: string;
    window_start: string;
    window_end: string;
  }) => void;
}

export default function BriefDayControls({
  day,
  adjacentDays,
  loading,
  activeEventId,
  onSelectDay,
  onSelectEvent,
}: Props) {
  return (
    <div className="an-day-controls" aria-label="Delivery day controls">
      <button
        type="button"
        className="an-day-controls__caret"
        onClick={() =>
          adjacentDays.previous && onSelectDay(adjacentDays.previous)
        }
        disabled={!adjacentDays.previous}
        aria-label="Previous available delivery day"
      >
        ‹
      </button>
      <Tooltip
        className="an-day-controls__date"
        placement="bottom"
        tip="This is the ERCOT market delivery date, not today’s calendar date or the date the DAM auction ran."
        aria-label="About the delivery date"
      >
        {day ? formatDay(day) : "Choose a delivery date"}
      </Tooltip>
      <button
        type="button"
        className="an-day-controls__caret"
        onClick={() => adjacentDays.next && onSelectDay(adjacentDays.next)}
        disabled={!adjacentDays.next}
        aria-label="Next available delivery day"
      >
        ›
      </button>
      <DateRangePicker
        singleDate
        showLabel={false}
        triggerLabel="Choose delivery date"
        selectedDate={day}
        onLoadDate={onSelectDay}
        onSelectEvent={onSelectEvent}
        events={CURATED_EVENTS}
        activeEventId={activeEventId}
        loading={loading}
      />
    </div>
  );
}
