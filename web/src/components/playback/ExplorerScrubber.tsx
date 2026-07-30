import { type ReactNode } from "react";
import PlaybackScrubber from "./PlaybackScrubber";
import DateRangePicker from "./DateRangePicker";
import { CURATED_EVENTS } from "../../lib/events";
import type { useExplorerSession } from "../../hooks/useExplorerSession";

// The one scrubber every page mounts: the full PlaybackScrubber (play, step,
// seek, sparkline) with the Load Window picker in its left slot, wired to a live
// session. Pages differ only by the optional rightSlot (Analysis passes its
// whole-day toggle). This is what makes the transport identical across Map,
// Matrix, and Analysis.
export default function ExplorerScrubber({
  session,
  rightSlot,
}: {
  session: ReturnType<typeof useExplorerSession>;
  rightSlot?: ReactNode;
}) {
  const {
    timestamps,
    currentIndex,
    setCurrentIndex,
    loading,
    sparkSeries,
    activeEventId,
    selectEvent,
    loadCustomWindow,
  } = session;
  return (
    <PlaybackScrubber
      timestamps={timestamps}
      currentIndex={currentIndex}
      onIndexChange={setCurrentIndex}
      loading={loading}
      sparkSeries={sparkSeries}
      eventLabel={
        CURATED_EVENTS.find((event) => event.id === activeEventId)?.label ?? null
      }
      leftSlot={
        <DateRangePicker
          onLoad={loadCustomWindow}
          onSelectEvent={selectEvent}
          events={CURATED_EVENTS}
          activeEventId={activeEventId}
          loading={loading}
        />
      }
      rightSlot={rightSlot}
    />
  );
}
