import type { MapDataMode, SpRow } from "../../api/types";
import type { LmpStats, CongestionStats } from "../../lib/colors";
import GridMap from "../../components/map/GridMap";
import Legend from "../../components/map/Legend";
import DetailCard from "../../components/map/DetailCard";
import { MapPaneBadge } from "./MapPaneBadge";
import type { MarketInteractions, PaneBadge } from "./mapPaneTypes";

interface MarketPaneProps {
  interactions: MarketInteractions;
  points: GeoJSON.FeatureCollection | null;
  rows: SpRow[];
  dataMode: MapDataMode;
  lmpStats: LmpStats | null;
  mcStats: CongestionStats | null;
  litCount: number;
  badge: PaneBadge;
  isMobile: boolean;
}

/** ERCOT's realized DAM map: the node's realized readout only, no SF drivers. */
export function MarketPane({
  interactions: ix, points, rows, dataMode, lmpStats, mcStats, litCount,
  badge, isMobile,
}: MarketPaneProps) {
  return (
    <>
      <GridMap
        points={points}
        rows={rows}
        dataMode={dataMode}
        lmpStats={lmpStats}
        mcStats={mcStats}
        side="actual"
        onMapClick={ix.onMapBackgroundClick}
        selectedSpId={ix.pinnedSp?.spId ?? null}
        onSpHover={ix.onSpHover}
        onSpClick={ix.onSpClick}
        onMapReady={ix.onMapReady}
        tapOnly={isMobile}
      />
      <MapPaneBadge
        cursorLabel={badge.cursorLabel}
        nodeCount={badge.nodeCount}
        emptyTopology={badge.emptyTopology}
        label="ERCOT: Day Ahead Market (DAM)"
        view="market"
        dataMode={dataMode}
        litCount={litCount}
        litNoun="priced"
        litHint="Nodes with a published ERCOT DAM settlement price (SPP) at this hour (colored on the map). Resource nodes (RN / CC / PUN) carry no published price, so this is fewer than the model's forecast count."
      />
      <Legend dataMode={dataMode} rows={rows} lmpStats={lmpStats} mcStats={mcStats} />
      {/* Actual card: the node's realized readout only — no SF drivers. */}
      <DetailCard
        hoveredSp={ix.hoveredSp}
        pinnedSp={ix.pinnedSp}
        valueMode="ercot"
        showDrivers={false}
        onClose={ix.onClearPinned}
        mobile={isMobile}
      />
    </>
  );
}
