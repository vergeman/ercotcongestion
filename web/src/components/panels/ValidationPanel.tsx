// The legacy bus-level `modeled_congestion` vs `basis` view was retired
// in 0047. The new `/validation` endpoint serves a zone-aggregated
// scorecard keyed by run_id; wiring it into the UI (run picker,
// per-zone tiles, hour scrubber, series overlay) is a follow-up plan.
//
// This component stays in the tree with its original Props signature
// so App.tsx doesn't need edits mid-stream; it renders a stub until
// the follow-up plan lands.

interface Props {
  start: Date | null;
  end: Date | null;
}

export default function ValidationPanel(_props: Props) {
  return (
    <div className="panel-empty label" style={{ padding: 16 }}>
      Scorecard panel pending — 0047 follow-up plan will wire the new
      zone-aggregated `/validation` payload (run picker, per-zone tiles,
      scrubber).
    </div>
  );
}
