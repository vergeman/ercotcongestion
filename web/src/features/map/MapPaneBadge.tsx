import type { ReactNode } from "react";
import type { MapDataMode, MapView } from "../../api/types";
import Tooltip from "../../components/ui/Tooltip";
import "./mapPresentation.css";

const VIEW_LABELS: Record<MapView, string> = {
  forecast: "Forecast", market: "Market", compare: "Compare", error: "Error",
};
const DATA_LABELS: Record<MapDataMode, string> = {
  congestion: "Congestion", lmp: "Price (LMP)",
};

interface MapPaneBadgeProps {
  label: string;
  view: MapView;
  dataMode: MapDataMode;
  cursorLabel: string;
  nodeCount: number;
  emptyTopology: boolean;
  litCount: number;
  litNoun: string;
  litHint: string;
  children?: ReactNode;
}

/** Presentational pane provenance and coverage badge shared by every map layout. */
export function MapPaneBadge({
  label, view, dataMode, cursorLabel, nodeCount, emptyTopology, litCount,
  litNoun, litHint, children,
}: MapPaneBadgeProps) {
  return <div className="pane-badge">
    <span className="pane-badge__title">{label}</span>
    <span className="pane-badge__coord mono">
      {VIEW_LABELS[view]} · {DATA_LABELS[dataMode]} · {cursorLabel}
    </span>
    <span className="pane-badge__meta">
      {emptyTopology ? <span className="pane-badge__stat">no nodes (rebuild topology cache)</span> : <>
        <Tooltip className="pane-badge__stat" tip="Settlement points (nodes) drawn on the map">
          <span className="pane-badge__key">nodes</span> <b>{nodeCount.toLocaleString()}</b>
        </Tooltip>
        <Tooltip className="pane-badge__stat" tip={litHint}>
          <span className="pane-badge__key">{litNoun}</span> <b>{litCount.toLocaleString()}</b>
        </Tooltip>
      </>}
    </span>
    {children}
  </div>;
}
