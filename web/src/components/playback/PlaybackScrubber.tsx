import { type ReactNode } from "react";
import TimeTransport from "./TimeTransport";
import type { SparkPoint } from "./TimelineSparkline";
import { formatCT } from "../../lib/time";

interface Props {
  timestamps: Date[];
  currentIndex: number;
  onIndexChange: (i: number | ((prev: number) => number)) => void;
  loading: boolean;
  sparkSeries: SparkPoint[];
  eventLabel?: string | null;
  leftSlot?: ReactNode;
  // A page-owned control in the transport's right column (e.g. the Analysis
  // whole-day toggle). Map/Matrix omit it.
  rightSlot?: ReactNode;
  // A one-shot playback request (0131), passed straight through to the
  // transport that owns `playing`.
  autoPlay?: boolean;
  onAutoPlayConsumed?: () => void;
}

// The Explorer (Map + Matrix) transport: the shared TimeTransport wired to the
// live rolling window with continuous play. Everything that used to live here —
// the markup, the play loop, the styles — now lives in TimeTransport; this file
// is just the explorer's configuration of it, so `App.tsx` is unchanged and the
// control renders exactly as before. The delivery-hour framing is the one thing
// specific to this domain, so it's supplied here.
export default function PlaybackScrubber({
  timestamps,
  currentIndex,
  onIndexChange,
  loading,
  sparkSeries,
  eventLabel,
  leftSlot,
  rightSlot,
  autoPlay,
  onAutoPlayConsumed,
}: Props) {
  return (
    <TimeTransport
      frames={timestamps}
      index={currentIndex}
      onSeek={onIndexChange}
      loading={loading}
      sparkSeries={sparkSeries}
      eventLabel={eventLabel}
      leftSlot={leftSlot}
      rightSlot={rightSlot}
      autoPlay={autoPlay}
      onAutoPlayConsumed={onAutoPlayConsumed}
      canPlay
      playIntervalMs={400}
      stepUnit="hour"
      axisLabel="Delivery hour"
      axisTip={
        <>
          The hourly settlement price power is priced <b>for</b>.
        </>
      }
      frameLabel={(t) => formatCT(t, "MMM d, yyyy HH:mm") + " CT"}
      rangeLabel={(t) => formatCT(t, "MMM d HH:mm")}
    />
  );
}
