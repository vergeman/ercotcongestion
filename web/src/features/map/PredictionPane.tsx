import type { MapOverview } from "../../api/types";
import GridMap from "../../components/map/GridMap";
import Legend from "../../components/map/Legend";
import DetailCard from "../../components/map/DetailCard";
import { MapPaneBadge } from "./MapPaneBadge";
import type {
  PaneBadge,
  PredictionInteractions,
  PredictionPaneConfig,
} from "./mapPaneTypes";

interface PredictionPaneProps {
  config: PredictionPaneConfig;
  interactions: PredictionInteractions;
  points: GeoJSON.FeatureCollection | null;
  overview: MapOverview | null;
  showConstraints: boolean;
  constraintsToggle?: { checked: boolean; onChange: (v: boolean) => void };
  cursorTs: Date | undefined;
  badge: PaneBadge;
  isMobile: boolean;
}

/**
 * The prediction map shared by the Forecast and Error views: the same GridMap
 * overlay, prediction DetailCard, constraint toggle, and member ring. Only the
 * rows/stats, data mode, error color, legend text, and preview badge differ —
 * all passed as `config`. Interaction ownership stays in MapWorkspace.
 */
export function PredictionPane({
  config, interactions: ix, points, overview, showConstraints,
  constraintsToggle, cursorTs, badge, isMobile,
}: PredictionPaneProps) {
  const hasOverlay = showConstraints && !!overview?.constraints.length;
  return (
    <>
      <GridMap
        points={points}
        rows={config.rows}
        dataMode={config.dataMode}
        lmpStats={config.lmpStats}
        mcStats={config.mcStats}
        onMapClick={ix.onMapBackgroundClick}
        selectedSpId={ix.pinnedSp?.spId ?? null}
        side="prediction"
        onSpHover={ix.onSpHover}
        onSpClick={ix.onSpClick}
        onMapReady={ix.onMapReady}
        showConstraints={showConstraints}
        reach={ix.reach}
        overview={overview}
        isolatedConstraint={ix.effectiveConstraintId}
        onIsolateConstraint={ix.onIsolateConstraint}
        onConstraintPreview={ix.onConstraintPreview}
        onConstraintSelect={ix.onConstraintSelect}
        focusReach={ix.focusReach}
        ringedSpId={isMobile ? null : ix.hoveredMemberSp}
        congestionColor={config.congestionColor}
        tapOnly={isMobile}
      />
      <MapPaneBadge
        cursorLabel={badge.cursorLabel}
        nodeCount={badge.nodeCount}
        emptyTopology={badge.emptyTopology}
        label={config.label}
        view={config.view}
        dataMode={config.dataMode}
        litCount={config.litCount}
        litNoun={config.litNoun}
        litHint={config.litHint}
      >
        {config.previewBadge && (
          <span className="pane-badge__preview" role="status">
            Preview — refreshes at noon CT
          </span>
        )}
      </MapPaneBadge>
      <Legend
        dataMode={config.dataMode}
        rows={config.rows}
        lmpStats={config.lmpStats}
        mcStats={config.mcStats}
        constraintOverlay={hasOverlay}
        overviewTypes={hasOverlay}
        constraintsToggle={constraintsToggle}
        lambdaIndicative={config.lambdaIndicative}
        titleOverride={config.titleOverride}
        signLabels={config.signLabels}
        barGradientOverride={config.barGradientOverride}
      />
      {/* Prediction card: the node's forecast / realized / error + SF drivers. */}
      <DetailCard
        hoveredSp={ix.hoveredSp}
        pinnedSp={ix.pinnedSp}
        valueMode="forecast"
        exposures={ix.exposures}
        exposuresLoading={ix.exposuresLoading}
        cursorTs={cursorTs}
        reach={ix.reach}
        onClose={ix.onClearPinned}
        onCloseReach={ix.onCloseReach}
        onSelectConstraint={ix.onConstraintSelect}
        onHoverConstraint={isMobile ? undefined : ix.onHoverConstraint}
        onHoverMember={isMobile ? undefined : ix.onHoverMember}
        onSelectMember={ix.onSelectMember}
        mobile={isMobile}
      />
    </>
  );
}
