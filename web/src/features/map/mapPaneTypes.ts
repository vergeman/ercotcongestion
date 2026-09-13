import type maplibregl from "maplibre-gl";
import type {
  SpRow,
  MapDataMode,
  MapView,
  ConstraintReach,
  ExposuresResponse,
} from "../../api/types";
import type { LmpStats, CongestionStats } from "../../lib/colors";
import type { Theme } from "../../lib/theme";
import type { HoveredSp } from "../../components/map/detail";

export type PaneSide = "prediction" | "actual";

// A hovered/pinned SP tagged with the pane it was touched on, so its card
// renders in that pane. The decomposition itself is side-independent.
export interface PaneSp extends HoveredSp {
  side: PaneSide;
}

type SpHover = (spId: string | null, props: Record<string, unknown> | null) => void;
type SpClick = (spId: string, props: Record<string, unknown>) => void;

// State and callbacks shared by every map pane. MapWorkspace owns the side-
// specific data so Forecast and Market cards can stay independent in Compare.
export interface MapPaneInteractions {
  hoveredSp: PaneSp | null;
  pinnedSp: PaneSp | null;
  reach: ConstraintReach | null;
  focusReach: ConstraintReach | null;
  effectiveConstraintId: string | null;
  exposures: ExposuresResponse | null;
  exposuresLoading: boolean;
  hoveredMemberSp: string | null;
  onMapBackgroundClick: () => void;
  onSpHover: SpHover;
  onSpClick: SpClick;
  onMapReady: (map: maplibregl.Map) => void;
  onIsolateConstraint: (id: string | null) => void;
  onConstraintPreview: (key: string | null) => void;
  onConstraintSelect: (key: string) => void;
  onClearPinned: () => void;
  onCloseReach: () => void;
  onHoverConstraint: (key: string | null) => void;
  onHoverMember: (sp: string | null) => void;
  onSelectMember: (sp: string) => void;
}

// Provenance/coverage badge inputs shared by every pane.
export interface PaneBadge {
  cursorLabel: string;
  nodeCount: number;
  emptyTopology: boolean;
}

// The data and readout differences between Forecast, Market, and Error.
export interface MapPaneConfig {
  view: MapView;
  side: PaneSide;
  valueMode: "forecast" | "ercot";
  rows: SpRow[];
  lmpStats: LmpStats | null;
  mcStats: CongestionStats | null;
  dataMode: MapDataMode;
  congestionColor?: (norm: number, theme: Theme) => string;
  label: string;
  litCount: number;
  litNoun: string;
  litHint: string;
  lambdaIndicative?: boolean;
  titleOverride?: string;
  signLabels?: { neg: string; pos: string };
  barGradientOverride?: string;
  previewBadge?: boolean;
}
