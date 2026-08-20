import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisBasis, AnalysisConstraintsResponse, AnalysisNodeResponse, AnalysisSettlementPointsResponse, MatrixFrame } from "../api/types";
import { getMatrixFrame } from "../api/matrixFrames";
import { getAnalysisNode } from "../api/analysisNode";
import { fetchAnalysisConstraints, fetchAnalysisSettlementPoints, fetchTopology } from "../api/client";
import MatrixGrid from "../components/matrix/MatrixGrid";
import MatrixLegend, { MatrixReachLegend } from "../components/matrix/MatrixLegend";
import MatrixReadDetail from "../components/matrix/MatrixReadDetail";
import MatrixSidebar, { type MatrixSidebarItem } from "../components/matrix/MatrixSidebar";
import MatrixBasisPanel from "../components/matrix/MatrixBasisPanel";
import Tooltip from "../components/ui/Tooltip";
import { basisFromNodes, type BasisResult } from "../lib/basis";
import {
  matrixMuSourceForVal,
  matrixValueModeForVal,
  type MatrixEntitySelection,
  type MatrixLens,
  type MatrixSelection,
  type MatrixTab,
  type MatrixValTab,
} from "../lib/matrix";
import { formatCT } from "../lib/time";

let rememberedTab: MatrixTab = "constraints";
let rememberedLens: MatrixLens = "read";
let rememberedVal: MatrixValTab = "sf";
let rememberedSelection: MatrixEntitySelection = null;
// The Basis lens's two node slots (0139/0006), persisted across a remount like
// the selection so a tab hop and back keeps the comparison. The active-slot
// pointer is derived from the fills on mount, not remembered.
let rememberedBasisA: string | null = null;
let rememberedBasisB: string | null = null;
let rememberedFrame: MatrixFrame | null = null;

const PIN_STORAGE_KEY = "ercotstress.matrix-pins.v1";
const MAX_PINS = 20;

function boundedPins(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].slice(0, MAX_PINS);
}

function storedPins(): { pinnedConstraints: string[]; pinnedSettlementPoints: string[] } {
  try {
    const value = JSON.parse(window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null") as { version?: number; constraints?: string[]; settlementPoints?: string[] } | null;
    if (value?.version === 1) return {
      pinnedConstraints: boundedPins(value.constraints ?? []),
      pinnedSettlementPoints: boundedPins(value.settlementPoints ?? []),
    };
  } catch {
    // A malformed old value is recoverable through Reset.
  }
  return { pinnedConstraints: [], pinnedSettlementPoints: [] };
}

// The working set is seeded from the defaults exactly once. This marker records
// that it happened, so emptying the set by hand stays empty on reload (the user
// chose "respect empty + Reset button") — only an explicit reset re-seeds.
function storedSeeded(): boolean {
  try {
    const value = JSON.parse(window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null") as { seeded?: boolean } | null;
    return value?.seeded === true;
  } catch {
    return false;
  }
}

interface WorkspaceState {
  tab: MatrixTab;
  lens: MatrixLens;
  val: MatrixValTab;
  query: string;
  fType: string;
  fZone: string;
  selection: MatrixEntitySelection;
  pinnedConstraints: string[];
  pinnedSettlementPoints: string[];
  // The Basis lens's two node slots. A sidebar click in the Basis lens fills the
  // `basisActiveSlot` slot and advances it (A→B→A), so one click sets A and the
  // next sets B; targeting a slot chip re-aims the next click.
  basisA: string | null;
  basisB: string | null;
  basisActiveSlot: "a" | "b";
}

function stateFromSearch(search: string): WorkspaceState {
  const params = new URLSearchParams(search);
  const stored = storedPins();
  const constraintKey = params.get("constraint");
  const sp = params.get("sp");
  const tabParam = params.get("tab");
  const tab: MatrixTab = tabParam === "nodes" || tabParam === "constraints"
    ? tabParam
    : sp && !constraintKey ? "nodes" : "constraints";
  const lensParam = params.get("lens");
  const valParam = params.get("val");
  // Basis is a Nodes-tab lens; a `?lens=basis` that lands on Constraints falls
  // back to Detail so the stage never shows an empty basis over a constraint list.
  const lens: MatrixLens = lensParam === "sf" ? "sf"
    : lensParam === "basis" ? (tab === "nodes" ? "basis" : "read")
    : "read";
  const basisA = params.get("sp_a") || null;
  const basisB = params.get("sp_b") || null;
  return {
    tab,
    lens,
    val: valParam === "fmu" || valParam === "dmu" ? valParam : "sf",
    query: (params.get("q") ?? params.get("constraint_search") ?? "").slice(0, 64),
    fType: params.get("type") ?? "",
    fZone: params.get("zone") ?? "",
    selection: constraintKey ? { kind: "constraint", key: constraintKey } : sp ? { kind: "node", point: sp } : null,
    pinnedConstraints: params.has("pinned_constraint") ? boundedPins(params.getAll("pinned_constraint")) : stored.pinnedConstraints,
    pinnedSettlementPoints: params.has("pinned_sp") ? boundedPins(params.getAll("pinned_sp")) : stored.pinnedSettlementPoints,
    basisA,
    basisB,
    // Arm the empty slot for the next click: B when only A is set, else A.
    basisActiveSlot: basisA && !basisB ? "b" : "a",
  };
}

function searchFromState(state: WorkspaceState): string {
  const params = new URLSearchParams();
  // Always emit tab. Omitting it for the "constraints" default let the read-back
  // in stateFromSearch re-infer the tab from a lingering `sp`/`constraint`
  // selection, which flipped a Nodes→Constraints toggle straight back to Nodes
  // whenever a node was still selected. Old links without `tab` still resolve
  // via that inference; new writes are explicit so the round-trip is stable.
  params.set("tab", state.tab);
  if (state.lens !== "read") params.set("lens", state.lens);
  if (state.val !== "sf") params.set("val", state.val);
  if (state.query) params.set("q", state.query);
  if (state.fType) params.set("type", state.fType);
  if (state.fZone) params.set("zone", state.fZone);
  // The working set (pins) is a personal saved board, persisted in localStorage
  // — deliberately NOT written to the URL, which kept the link short. Old links
  // that still carry `pinned_constraint`/`pinned_sp` are read back in
  // stateFromSearch for backward compatibility; we just stop emitting them.
  if (state.selection?.kind === "constraint") params.set("constraint", state.selection.key);
  if (state.selection?.kind === "node") params.set("sp", state.selection.point);
  // The Basis lens's node pair — makes a comparison shareable, independent of
  // the read/SF `sp` selection. Old links (no `sp_a`/`sp_b`) resolve unchanged.
  if (state.basisA) params.set("sp_a", state.basisA);
  if (state.basisB) params.set("sp_b", state.basisB);
  const query = params.toString();
  return query ? `?${query}` : "";
}

interface Props {
  timestamp: Date | null;
  routeSearch: string;
  onSelectionRouteChange: (search: string) => void;
  onNavigateToMap: (search: string) => void;
}

function moneyLabel(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

export default function MatrixWorkspace({ timestamp, routeSearch, onSelectionRouteChange, onNavigateToMap }: Props) {
  const [frame, setFrame] = useState<MatrixFrame | null>(() =>
    rememberedFrame?.interval_ts === timestamp?.toISOString() ? rememberedFrame : null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [state, setState] = useState<WorkspaceState>(() => {
    const params = new URLSearchParams(routeSearch);
    const fromRoute = stateFromSearch(routeSearch);
    return {
      ...fromRoute,
      tab: params.has("tab") || params.has("sp") || params.has("constraint") ? fromRoute.tab : rememberedTab,
      lens: params.has("lens") ? fromRoute.lens : rememberedLens,
      val: params.has("val") ? fromRoute.val : rememberedVal,
      selection: fromRoute.selection ?? rememberedSelection,
      basisA: params.has("sp_a") ? fromRoute.basisA : rememberedBasisA,
      basisB: params.has("sp_b") ? fromRoute.basisB : rememberedBasisB,
    };
  });
  const [constraintsResp, setConstraintsResp] = useState<AnalysisConstraintsResponse | null>(null);
  const [nodeMeta, setNodeMeta] = useState<Map<string, { type: string | null; zone: string | null }>>(new Map());
  const [settlementPointsResp, setSettlementPointsResp] = useState<AnalysisSettlementPointsResponse | null>(null);
  const [seeded, setSeeded] = useState<boolean>(() => storedSeeded());
  // The preview key the *currently displayed* frame is hoisted by. It lags the
  // live selection during a peek fetch so the grid never un-hoists the old
  // preview (dropping it to the bottom) before the new one's data has arrived.
  const [frameTopKey, setFrameTopKey] = useState<string | null>(null);
  const requestId = useRef(0);

  // The current preview (the "top row"): the explicitly selected sidebar entity.
  // When it is not already in the working set it rides in via `peek` — a forced
  // row/column beyond the pin cap — and is rendered un-pinned until pinned.
  const previewConstraintKey = state.selection?.kind === "constraint" ? state.selection.key : null;
  const previewNodeKey = state.selection?.kind === "node" ? state.selection.point : null;
  const peekConstraint = previewConstraintKey && !state.pinnedConstraints.includes(previewConstraintKey) ? previewConstraintKey : null;
  const peekSettlementPoint = previewNodeKey && !state.pinnedSettlementPoints.includes(previewNodeKey) ? previewNodeKey : null;

  useEffect(() => {
    if (!timestamp) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    setLoading(true);
    setError(null);

    // Two fetch modes. SEED (first load, never seeded, empty set): rank the
    // default anchor board once so we can adopt it as the working set. WORKING
    // SET (thereafter): fetch exactly the pinned entities, plus the previewed
    // top row via peek. The Constraints/Nodes tab transposes the WORKING SET
    // frame client-side, so a toggle never refetches.
    const workingSetEmpty = state.pinnedConstraints.length === 0 && state.pinnedSettlementPoints.length === 0;
    const seeding = !seeded && workingSetEmpty;
    const request = seeding
      ? {
          rowPreset: "top30" as const, rowLimit: 8, columnLimit: 30,
          columnSet: "default_anchors" as const, rowOrder: "anchor_contribution" as const,
        }
      : {
          rowPreset: "pinned" as const, columnSet: "pinned" as const, rowLimit: 8, columnLimit: 30,
          pinnedConstraints: state.pinnedConstraints,
          pinnedSettlementPoints: state.pinnedSettlementPoints,
          peekConstraint, peekSettlementPoint,
        };

    void getMatrixFrame(timestamp, request, controller.signal)
      .then((nextFrame) => {
        if (id !== requestId.current) return;
        rememberedFrame = nextFrame;
        setFrame(nextFrame);
        // Adopt the seed as the working set exactly once; from here the set is
        // user-owned and the fetch flips to WORKING SET mode.
        if (seeding && nextFrame.available && (nextFrame.rows.length > 0 || nextFrame.columns.length > 0)) {
          setSeeded(true);
          update({
            pinnedConstraints: boundedPins(nextFrame.rows.map((row) => row.constraint_key)),
            pinnedSettlementPoints: boundedPins(nextFrame.columns.map((column) => column.settlement_point)),
          });
        }
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof Error && requestError.name === "AbortError") return;
        if (id === requestId.current) {
          setError("The Matrix frame could not be loaded. Check the connection and retry.");
        }
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false);
      });
    return () => controller.abort();
    // Deliberately NOT keyed on state.tab: the tab transposes the fetched frame
    // client-side, so a toggle must reuse the same frame, not refetch a new one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seeded, state.pinnedConstraints, state.pinnedSettlementPoints, peekConstraint, peekSettlementPoint, requestVersion, timestamp]);

  // The preview entity of the current row axis, and whether it is actually
  // present in the frame on screen. A freshly clicked, not-yet-fetched preview
  // is absent until its peek resolves.
  const liveTopKey = state.tab === "nodes" ? previewNodeKey : previewConstraintKey;
  const liveInFrame = Boolean(liveTopKey && (state.tab === "nodes"
    ? frame?.columns.some((column) => column.settlement_point === liveTopKey)
    : frame?.rows.some((row) => row.constraint_key === liveTopKey)));
  // Record the preview only once it is in the frame, so during the next peek's
  // load we keep hoisting the still-present previous preview instead of dropping
  // it — the grid stays put and the new preview lands directly at the top.
  useEffect(() => {
    if (liveInFrame && liveTopKey) setFrameTopKey(liveTopKey);
  }, [liveInFrame, liveTopKey]);
  const topRowKey = liveInFrame ? liveTopKey : frameTopKey;
  const topRowPinned = topRowKey
    ? (state.tab === "nodes" ? state.pinnedSettlementPoints : state.pinnedConstraints).includes(topRowKey)
    : false;
  const previewKey = topRowKey && !topRowPinned ? topRowKey : null;

  // The topology's sp_type/load_zone properties are the only source of node
  // type/zone metadata — /analysis/settlement-points is deliberately a bare
  // vocabulary list. Fetched once; it does not vary with the current run.
  useEffect(() => {
    let cancelled = false;
    void fetchTopology()
      .then((topology) => {
        if (cancelled) return;
        const collection = (topology as { settlement_points?: { features?: Array<{ properties?: Record<string, unknown> }> } }).settlement_points;
        const next = new Map<string, { type: string | null; zone: string | null }>();
        for (const feature of collection?.features ?? []) {
          const props = feature.properties ?? {};
          const spId = props.sp_id;
          if (typeof spId !== "string") continue;
          next.set(spId, {
            type: typeof props.sp_type === "string" ? props.sp_type : null,
            zone: typeof props.load_zone === "string" ? props.load_zone : null,
          });
        }
        setNodeMeta(next);
      })
      .catch(() => { /* Node type/zone filters degrade to empty, not an error. */ });
    return () => { cancelled = true; };
  }, []);

  // The sidebar's full vocabulary depends on which day's artifact the frame
  // resolved to, so it follows the frame rather than the raw timestamp.
  useEffect(() => {
    if (!frame?.available) { setConstraintsResp(null); setSettlementPointsResp(null); return; }
    let cancelled = false;
    void fetchAnalysisConstraints(frame.delivery_date, { runId: frame.run_id })
      .then((response) => { if (!cancelled) setConstraintsResp(response); })
      .catch(() => { if (!cancelled) setConstraintsResp(null); });
    void fetchAnalysisSettlementPoints(frame.delivery_date, { runId: frame.run_id })
      .then((response) => { if (!cancelled) setSettlementPointsResp(response); })
      .catch(() => { if (!cancelled) setSettlementPointsResp(null); });
    return () => { cancelled = true; };
  }, [frame?.delivery_date, frame?.run_id, frame?.available]);

  useEffect(() => {
    try {
      window.localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify({
        version: 1, seeded, constraints: state.pinnedConstraints, settlementPoints: state.pinnedSettlementPoints,
      }));
    } catch {
      // Local persistence is deliberately optional; URL state remains usable.
    }
  }, [seeded, state.pinnedConstraints, state.pinnedSettlementPoints]);

  const update = (patch: Partial<WorkspaceState>) => {
    setState((current) => {
      const next = { ...current, ...patch };
      rememberedTab = next.tab; rememberedLens = next.lens; rememberedVal = next.val;
      rememberedSelection = next.selection;
      rememberedBasisA = next.basisA; rememberedBasisB = next.basisB;
      onSelectionRouteChange(searchFromState(next));
      return next;
    });
  };

  const damPending = frame?.dam_status === "pending";
  useEffect(() => {
    if (state.val === "dmu" && damPending) update({ val: "fmu" });
    // `update` is stable across renders; including it would fire on every
    // selection/filter change, not just the DAM-availability flip this
    // effect exists to react to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [damPending]);

  // Selection and filter state are URL-addressable. A hidden selection
  // remains explicit instead of being erased when a filter changes its frame.
  useEffect(() => {
    const next = stateFromSearch(routeSearch);
    rememberedTab = next.tab; rememberedLens = next.lens; rememberedVal = next.val;
    rememberedSelection = next.selection;
    rememberedBasisA = next.basisA; rememberedBasisB = next.basisB;
    setState(next);
  }, [routeSearch]);

  const isPinned = (value: string, kind: "constraint" | "sp") =>
    (kind === "constraint" ? state.pinnedConstraints : state.pinnedSettlementPoints).includes(value);
  const togglePin = (value: string, kind: "constraint" | "sp") => {
    const key = kind === "constraint" ? "pinnedConstraints" : "pinnedSettlementPoints";
    const values = state[key];
    // New pins prepend to the TOP of the working set and nothing re-sorts — so a
    // just-pinned item stays where it was previewed (top), and the next preview
    // pushes it to row #2 rather than banishing it to the bottom of the list.
    update({ [key]: isPinned(value, kind) ? values.filter((item) => item !== value) : boundedPins([value, ...values]) });
  };

  const constraintItems = useMemo<MatrixSidebarItem[]>(() => {
    const rows = constraintsResp?.available ? constraintsResp.rows ?? [] : [];
    return [...rows]
      .sort((a, b) => a.daily_mu_rank - b.daily_mu_rank)
      .map((row) => ({
        id: row.constraint_key,
        label: row.name,
        sub: row.contingency,
        type: row.ctype,
        zone: row.zone,
        sizeLabel: moneyLabel(row.daily_mu_sum),
        pinned: isPinned(row.constraint_key, "constraint"),
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [constraintsResp, state.pinnedConstraints]);

  const nodeItems = useMemo<MatrixSidebarItem[]>(() => {
    const points = settlementPointsResp?.available ? settlementPointsResp.settlement_points ?? [] : [];
    return [...points].sort((a, b) => a.localeCompare(b)).map((point) => {
      const meta = nodeMeta.get(point);
      return {
        id: point,
        label: point,
        sub: null,
        type: meta?.type ?? null,
        zone: meta?.zone ?? null,
        sizeLabel: null,
        pinned: isPinned(point, "sp"),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settlementPointsResp, nodeMeta, state.pinnedSettlementPoints]);

  const fullItems = state.tab === "constraints" ? constraintItems : nodeItems;
  const typeOptions = useMemo(
    () => [...new Set(fullItems.map((item) => item.type).filter((t): t is string => Boolean(t)))].sort(),
    [fullItems]
  );
  const zoneOptions = useMemo(
    () => [...new Set(fullItems.map((item) => item.zone).filter((z): z is string => Boolean(z)))].sort(),
    [fullItems]
  );
  const filteredItems = useMemo(() => {
    const q = state.query.trim().toLowerCase();
    return fullItems.filter((item) => {
      if (state.fType && item.type !== state.fType) return false;
      if (state.fZone && item.zone !== state.fZone) return false;
      if (q) {
        const haystack = `${item.id} ${item.label} ${item.sub ?? ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [fullItems, state.query, state.fType, state.fZone]);

  const effectiveSelection: MatrixEntitySelection = state.selection ?? (fullItems.length
    ? (state.tab === "constraints" ? { kind: "constraint", key: fullItems[0].id } : { kind: "node", point: fullItems[0].id })
    : null);

  const selectedIdForSidebar = state.tab === "constraints"
    ? (effectiveSelection?.kind === "constraint" ? effectiveSelection.key : null)
    : (effectiveSelection?.kind === "node" ? effectiveSelection.point : null);

  const selectedConstraintRow = effectiveSelection?.kind === "constraint"
    ? constraintsResp?.available ? constraintsResp.rows?.find((row) => row.constraint_key === effectiveSelection.key) ?? null : null
    : null;
  const selectedNodeMeta = effectiveSelection?.kind === "node" ? nodeMeta.get(effectiveSelection.point) ?? null : null;

  // Basis lens (0139/0006): two node slots A and B, filled by clicks in the
  // sidebar index (the active slot advances A→B→A). The lens is Nodes-tab only;
  // A/B are their own state, decoupled from the read/SF `selection`.
  const showBasis = state.lens === "basis" && state.tab === "nodes";
  // μ follows the value sub-toggle: predicted carries Forecast μ, realized
  // carries ERCOT DAM μ. DAM→forecast fallback already happens upstream (the
  // `damPending` effect flips `val` off dmu), so `val==="dmu"` implies DAM data.
  const basisBasis: AnalysisBasis = state.val === "dmu" ? "realized" : "predicted";
  const [basisResult, setBasisResult] = useState<BasisResult | null>(null);
  // The realized (settled DAM) basis total for the same pair, shown alongside a
  // forecast basis and used as the settled reconciliation denominator.
  const [basisRealizedTotal, setBasisRealizedTotal] = useState<number | null>(null);
  const [basisLoading, setBasisLoading] = useState(false);
  const basisRequestId = useRef(0);

  useEffect(() => {
    // Compute only once both slots are set. A one-sided constraint still counts,
    // so we fetch both columns and union them in `basisFromNodes`.
    if (!showBasis || !state.basisA || !state.basisB || !timestamp || !frame?.delivery_date) {
      setBasisResult(null); setBasisRealizedTotal(null); setBasisLoading(false);
      return;
    }
    const controller = new AbortController();
    const id = ++basisRequestId.current;
    setBasisLoading(true);
    const hour = timestamp.toISOString();
    const deliveryDate = frame.delivery_date;
    const runId = frame.run_id ?? undefined;
    const aNode = state.basisA;
    const bNode = state.basisB;
    // getAnalysisNode is LRU-cached by (point, day, hour, basis, run), so
    // sweeping one slot against a held other refetches only the changed side.
    const fetchPair = (basis: AnalysisBasis): Promise<[AnalysisNodeResponse, AnalysisNodeResponse]> =>
      Promise.all([
        getAnalysisNode(aNode, deliveryDate, hour, basis, runId, controller.signal),
        getAnalysisNode(bNode, deliveryDate, hour, basis, runId, controller.signal),
      ]);
    // When the toggle shows the forecast basis and settled DAM exists, also join
    // the realized pair so the panel can show forecast vs settled side by side.
    const wantRealized = basisBasis === "predicted" && frame.dam_status === "available";
    fetchPair(basisBasis)
      .then(async ([a, b]) => {
        if (id !== basisRequestId.current) return;
        const primary = basisFromNodes(a, b);
        let realizedTotal: number | null = null;
        if (wantRealized) {
          try {
            const [ar, br] = await fetchPair("realized");
            if (id !== basisRequestId.current) return;
            realizedTotal = basisFromNodes(ar, br).total;
          } catch {
            // Realized is an optional side-by-side; its absence is not an error.
          }
        }
        setBasisResult(primary);
        setBasisRealizedTotal(realizedTotal);
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        if (id === basisRequestId.current) { setBasisResult(null); setBasisRealizedTotal(null); }
      })
      .finally(() => { if (id === basisRequestId.current) setBasisLoading(false); });
    return () => controller.abort();
  }, [showBasis, state.basisA, state.basisB, basisBasis, timestamp, frame?.delivery_date, frame?.run_id, frame?.dam_status]);

  // A sidebar click fills the active basis slot (and advances it) when the Basis
  // lens is up; otherwise it drives the ordinary read/SF selection.
  const selectId = (id: string) => {
    if (showBasis) {
      if (state.basisActiveSlot === "a") update({ basisA: id, basisActiveSlot: "b" });
      else update({ basisB: id, basisActiveSlot: "a" });
      return;
    }
    update({ selection: state.tab === "constraints" ? { kind: "constraint", key: id } : { kind: "node", point: id } });
  };
  const handleGridSelect = (gridSelection: MatrixSelection) => {
    if (!gridSelection) return;
    if (gridSelection.kind === "constraint") { update({ selection: { kind: "constraint", key: gridSelection.constraintKey } }); return; }
    if (gridSelection.kind === "settlementPoint") { update({ selection: { kind: "node", point: gridSelection.settlementPoint } }); return; }
    update({ selection: state.tab === "nodes" ? { kind: "node", point: gridSelection.settlementPoint } : { kind: "constraint", key: gridSelection.constraintKey } });
  };
  const basisTargetSlot = (slot: "a" | "b") => update({ basisActiveSlot: slot });
  const basisSwap = () => update({ basisA: state.basisB, basisB: state.basisA });
  const basisClear = (slot: "a" | "b") => update(slot === "a" ? { basisA: null, basisActiveSlot: "a" } : { basisB: null, basisActiveSlot: "b" });
  // Clearing `seeded` puts the fetch back into SEED mode, so the defaults are
  // re-adopted as a fresh working set. (Emptying the set item-by-item leaves
  // `seeded` true, so a hand-emptied set stays empty on reload — the user's
  // "respect empty + Reset button" choice.)
  const resetToDefaults = () => {
    setSeeded(false);
    update({ query: "", fType: "", fZone: "", selection: null, pinnedConstraints: [], pinnedSettlementPoints: [] });
  };

  const valueMode = matrixValueModeForVal(state.val);
  const muSource = matrixMuSourceForVal(state.val);
  const legendMax = frame?.available
    ? (valueMode === "sf" ? frame.sf_day_max_abs : frame.contribution_day_max_abs)
    : 0;

  // The grid highlights and previews only the EXPLICIT selection (the current
  // sidebar/grid click), not the Read lens's first-item fallback — an explicit
  // selection is always peeked into the frame, so it is the top row, never
  // "hidden". Nothing is highlighted until the user actually picks something.
  const gridSelection: MatrixSelection = state.selection?.kind === "constraint"
    ? { kind: "constraint", constraintKey: state.selection.key }
    : state.selection?.kind === "node"
      ? { kind: "settlementPoint", settlementPoint: state.selection.point }
      : null;

  const isUsable = frame?.available && frame.rows.length > 0 && frame.columns.length > 0;
  const isUnavailable = frame && !frame.available;
  const isEmpty = frame?.available && !isUsable;
  const damUnmatchedRows = frame?.rows.filter((row) => row.ercot_dam_mu == null).length ?? 0;

  return (
    <main className="matrix-workspace" aria-labelledby="matrix-title">
      <div className="matrix-workspace__heading">
        <span className="label">Explorer / matrix</span>
        <h1 id="matrix-title">Constraint × settlement point</h1>
        <p>{timestamp ? `${formatCT(timestamp, "MMM d, yyyy HH:mm")} CT` : "Waiting for playback data"}</p>
      </div>

      {loading && !frame && !error && <div className="matrix-workspace__loading" role="status">Loading matrix frame…</div>}
      {error && (
        <section className="matrix-workspace__state" role="alert">
          <h2>Unable to load Matrix</h2>
          <p>{error}</p>
          <button type="button" onClick={() => setRequestVersion((version) => version + 1)}>Retry</button>
        </section>
      )}
      {!error && isUnavailable && frame && (
        <section className="matrix-workspace__state" role="status">
          <h2>Matrix unavailable for this hour</h2>
          <p>{frame.unavailable_reason === "artifact_missing" ? "No causal daily Matrix artifact was published for this delivery day." : "This timestamp is outside the available Matrix artifact."}</p>
        </section>
      )}
      {!error && isEmpty && (
        <section className="matrix-workspace__state" role="status">
          <h2>No bounded Matrix values</h2>
          <p>The selected artifact contains no rows or settlement-point columns for this bounded view.</p>
        </section>
      )}

      {!error && isUsable && frame && (
        <div className="matrix-workspace__body">
          <MatrixSidebar
            tab={state.tab}
            items={filteredItems}
            totalCount={fullItems.length}
            selectedId={showBasis ? null : selectedIdForSidebar}
            basisSlots={showBasis ? { a: state.basisA, b: state.basisB } : undefined}
            onSelect={selectId}
            onTab={(tab) => update(tab === "constraints" && state.lens === "basis" ? { tab, lens: "read" } : { tab })}
            query={state.query}
            onQuery={(query) => update({ query })}
            fType={state.fType}
            fZone={state.fZone}
            typeOptions={typeOptions}
            zoneOptions={zoneOptions}
            onFilter={(next) => update(next)}
            onTogglePin={(id) => togglePin(id, state.tab === "constraints" ? "constraint" : "sp")}
            onReset={resetToDefaults}
          />
          <section className="matrix-workspace__stage" aria-busy={loading}>
            <header className="matrix-workspace__stage-header">
              <div className="matrix-workspace__toggle" role="tablist" aria-label="Lens">
                <button type="button" role="tab" aria-selected={state.lens === "read"} className={state.lens === "read" ? "is-active" : ""} onClick={() => update({ lens: "read" })}>Detail</button>
                <button type="button" role="tab" aria-selected={state.lens === "sf"} className={state.lens === "sf" ? "is-active" : ""} onClick={() => update({ lens: "sf" })}>SF</button>
                {state.tab !== "nodes" ? (
                  <Tooltip
                    as="span"
                    className="matrix-workspace__disabled-tab"
                    tip="Basis is available only on the Nodes tab because it compares two settlement points."
                  >
                    <button type="button" role="tab" aria-selected={false} disabled>Basis</button>
                  </Tooltip>
                ) : (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={state.lens === "basis"}
                    className={state.lens === "basis" ? "is-active" : ""}
                    onClick={() => update({ lens: "basis" })}
                  >Basis</button>
                )}
              </div>
              {state.lens === "sf" && (
                <div className="matrix-workspace__toggle matrix-workspace__toggle--data" role="group" aria-label="Value">
                  <span className="label matrix-workspace__toggle-label">Data</span>
                  <button type="button" className={state.val === "sf" ? "is-active" : ""} onClick={() => update({ val: "sf" })}>Shift Factor</button>
                  <button type="button" className={state.val === "fmu" ? "is-active" : ""} onClick={() => update({ val: "fmu" })}>Forecast μ</button>
                  <button type="button" disabled={damPending} title={damPending ? "ERCOT DAM μ has not been published for this hour" : undefined} className={state.val === "dmu" ? "is-active" : ""} onClick={() => update({ val: "dmu" })}>ERCOT DAM μ</button>
                </div>
              )}
              {state.lens === "basis" && (
                <div className="matrix-workspace__toggle matrix-workspace__toggle--data" role="group" aria-label="Basis μ source">
                  <span className="label matrix-workspace__toggle-label">Data</span>
                  <button type="button" className={state.val !== "dmu" ? "is-active" : ""} onClick={() => update({ val: "fmu" })}>Forecast μ</button>
                  <button type="button" disabled={damPending} title={damPending ? "ERCOT DAM μ has not been published for this hour" : undefined} className={state.val === "dmu" ? "is-active" : ""} onClick={() => update({ val: "dmu" })}>ERCOT DAM μ</button>
                </div>
              )}
              {state.lens === "read" && <MatrixReachLegend />}
              {state.lens === "sf" && <MatrixLegend mode={valueMode} maxAbs={legendMax} />}
              {/* Basis has no legend, but an invisible legend-shaped placeholder
                  keeps the header the same height as the Detail/SF lenses so the
                  controls row does not resize when you switch lenses. */}
              {state.lens === "basis" && (
                <div className="matrix-legend" aria-hidden="true" style={{ visibility: "hidden" }}>
                  <div className="matrix-legend__title label">&nbsp;</div>
                  <div className="matrix-legend__bar" />
                  <div className="matrix-legend__ticks mono"><span>&nbsp;</span></div>
                  <div className="matrix-legend__signs label"><span>&nbsp;</span></div>
                </div>
              )}
            </header>

            {state.lens === "read" && (
              <div className="matrix-workspace__read">
                <MatrixReadDetail
                  selection={effectiveSelection}
                  timestamp={timestamp}
                  val={state.val}
                  deliveryDate={frame.delivery_date}
                  runId={frame.run_id}
                  damStatus={frame.dam_status}
                  constraintRow={selectedConstraintRow}
                  nodeMeta={selectedNodeMeta}
                  onNavigateToMap={onNavigateToMap}
                />
              </div>
            )}

            {state.lens === "sf" && (
              <>
                <div className="matrix-workspace__meta">
                  <span>Run {frame.run_id}</span>
                  <span>Delivery day {frame.delivery_date}</span>
                  <span>{frame.rows.length} of {frame.total_constraint_count} constraints</span>
                  <span>{frame.columns.length} of {frame.total_settlement_point_count} settlement points</span>
                  {loading && <span>Updating frame…</span>}
                </div>
                <div className={`matrix-workspace__notices${valueMode === "contribution" && frame.dam_status !== "available" ? " has-notices" : ""}`}>
                  {valueMode === "contribution" && frame.dam_status === "pending" && (
                    <div className="matrix-workspace__notice" role="status">ERCOT DAM μ is pending; Contribution uses Forecast μ.</div>
                  )}
                  {valueMode === "contribution" && frame.dam_status === "partial" && (
                    <div className="matrix-workspace__notice" role="status">DAM μ: {frame.rows.length - damUnmatchedRows}/{frame.rows.length} constraints matched; unmatched cells are unavailable.</div>
                  )}
                </div>
                <MatrixGrid
                  frame={frame}
                  orientation={state.tab === "nodes" ? "nodes" : "constraints"}
                  topRowKey={topRowKey}
                  previewKey={previewKey}
                  mode={valueMode}
                  muSource={muSource}
                  selection={gridSelection}
                  maxAbs={legendMax}
                  onSelect={handleGridSelect}
                  isPinned={(item) => isPinned(item.key, item.kind === "constraint" ? "constraint" : "sp")}
                  onTogglePin={(item) => togglePin(item.key, item.kind === "constraint" ? "constraint" : "sp")}
                />
              </>
            )}

            {state.lens === "basis" && (
              <MatrixBasisPanel
                aNode={state.basisA}
                bNode={state.basisB}
                activeSlot={state.basisActiveSlot}
                loading={basisLoading}
                primary={basisResult}
                realizedTotal={basisBasis === "predicted" ? basisRealizedTotal : null}
                settledBasis={basisBasis === "predicted" ? basisRealizedTotal : null}
                onTargetSlot={basisTargetSlot}
                onSwap={basisSwap}
                onClear={basisClear}
              />
            )}
          </section>
        </div>
      )}

      {!timestamp && !loading && (
        <section className="matrix-workspace__state" role="status">
          <h2>Waiting for a playback hour</h2>
          <p>Choose an available timestamp in the shared playback scrubber to load its Matrix frame.</p>
        </section>
      )}

      <style>{`
        .matrix-workspace { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 16px; gap: 12px; background: var(--bg-base); }
        .matrix-workspace__heading { min-width: 0; flex: 0 0 auto; }
        .matrix-workspace h1 { margin: 3px 0; font: 600 var(--fs-xl)/1.2 var(--font-label); color: var(--text-primary); }
        .matrix-workspace p { color: var(--text-secondary); font-size: var(--fs-label); margin: 0; }
        .matrix-workspace button { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font: 500 var(--fs-label) var(--font-sans); padding: 6px 8px; }
        .matrix-workspace__toggle { display: flex; align-items: center; gap: 7px; }
        .matrix-workspace__toggle--data { gap: 4px; }
        .matrix-workspace__disabled-tab { display: inline-flex; }
        .matrix-workspace__toggle-label { margin-right: 4px; }
        .matrix-workspace__toggle button { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-secondary); font-weight: 600; padding: 7px 11px; }
        .matrix-workspace__toggle button.is-active { background: var(--accent-dim); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); color: var(--accent); }
        .matrix-workspace button:disabled { cursor: not-allowed; color: var(--text-muted); }
        .matrix-workspace__loading { display: grid; flex: 1; place-items: center; color: var(--text-secondary); }
        .matrix-workspace__state { align-self: center; background: var(--bg-panel); border: 1px solid var(--border); box-shadow: var(--shadow-panel); max-width: 500px; padding: 22px; width: min(500px, 100%); }
        .matrix-workspace__state h2 { font: 600 var(--fs-lg) var(--font-label); margin: 0 0 8px; }
        .matrix-workspace__state p { line-height: 1.45; }
        .matrix-workspace__state button { background: var(--accent-dim); color: var(--accent); margin-top: 14px; }
        .matrix-workspace__body { display: flex; flex: 1; min-height: 0; gap: 0; }
        .matrix-workspace__stage { display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; border: 1px solid var(--border); background: var(--bg-panel); overflow: hidden; }
        .matrix-workspace__stage-header { align-items: center; border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 10px; }
        .matrix-workspace__read { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0 0 0 18px; }
        .matrix-workspace__meta { color: var(--text-secondary); display: flex; flex-wrap: wrap; font-size: var(--fs-label); gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--border); }
        .matrix-workspace__notices { min-height: 0; }
        .matrix-workspace__notices.has-notices { border-bottom: 1px solid var(--border); display: grid; gap: 1px; }
        .matrix-workspace__notice { background: var(--accent-dim); color: var(--text-secondary); font-size: var(--fs-label); padding: 5px 10px; }
        .matrix-legend { flex: 0 0 240px; width: 240px; margin-left: auto; }
        .matrix-legend__title { color: var(--text-secondary); margin-bottom: 4px; }
        .matrix-legend__bar { height: 8px; }
        .matrix-legend__ticks, .matrix-legend__signs { display: flex; justify-content: space-between; font-size: 9px; margin-top: 3px; }
        .matrix-legend__signs { color: var(--text-secondary); }
        .matrix-grid { overflow: auto; min-height: 0; flex: 1; outline: none; }
        .matrix-grid:focus-visible, .matrix-grid [tabindex="0"]:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; position: relative; z-index: 3; }
        .matrix-grid table { border-collapse: separate; border-spacing: 0; font-size: var(--fs-micro); width: max-content; }
        .matrix-grid th, .matrix-grid td { border-right: 1px solid color-mix(in srgb, var(--border) 70%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
        .matrix-grid thead th { background: var(--bg-panel); position: sticky; top: 0; z-index: 2; height: 50px; vertical-align: bottom; }
        .matrix-grid__corner { left: 0; z-index: 4 !important; min-width: 205px; padding: 7px 10px; text-align: left; }
        .matrix-grid__corner span, .matrix-grid__row span { display: block; color: var(--text-primary); font-weight: 600; }
        .matrix-grid small { color: var(--text-secondary); display: block; font-size: 9px; font-weight: 400; margin-top: 2px; }
        .matrix-grid__column { min-width: 72px; max-width: 72px; cursor: pointer; padding: 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__column > span { color: var(--text-primary); display: block; overflow: hidden; text-overflow: ellipsis; }
        .matrix-grid__row { background: var(--bg-panel); cursor: pointer; left: 0; min-width: 205px; max-width: 205px; padding: 6px 10px; position: sticky; text-align: left; z-index: 1; }
        .matrix-grid__row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .matrix-grid__cell { color: #172033; cursor: pointer; font: 600 var(--fs-micro) var(--font-mono); min-width: 72px; padding: 7px 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__cell--unavailable { color: var(--text-muted); background: repeating-linear-gradient(-45deg, var(--bg-surface), var(--bg-surface) 3px, var(--bg-panel) 3px, var(--bg-panel) 6px) !important; }
        .matrix-grid__column[aria-selected="true"] { background: color-mix(in srgb, var(--accent-dim) 72%, var(--bg-panel)); box-shadow: inset 0 -3px var(--accent); }
        .matrix-grid__row[aria-selected="true"] { background: color-mix(in srgb, var(--accent-dim) 72%, var(--bg-panel)); box-shadow: inset 3px 0 var(--accent); }
        .matrix-grid__cell.is-selected { box-shadow: inset 0 0 0 3px var(--accent); position: relative; z-index: 1; }
        /* Both shadow prices side by side; the active source is emphasized so
           the comparison reads without hiding the other one (0145). */
        .matrix-grid__mu { display: flex; gap: 6px; flex-wrap: wrap; }
        .matrix-grid__mu .is-active { color: var(--text); font-weight: 600; }
        .matrix-grid__rank { color: var(--text-muted); }
        .matrix-grid__basis { color: var(--text-muted); font-style: italic; }
        /* An SF pinned at the fit's clip is a bound, not a measurement. */
        .matrix-grid__clip { color: var(--text-muted); padding-left: 1px; }
        @media (max-width: 767px) { .matrix-workspace { padding: 10px; } .matrix-workspace__body { flex-direction: column; } .matrix-grid__corner, .matrix-grid__row { min-width: 155px; max-width: 155px; } .matrix-grid::before { color: var(--text-secondary); content: "Scroll horizontally to inspect settlement points"; display: block; font-size: var(--fs-micro); padding: 5px 8px; position: sticky; left: 0; } }
      `}</style>
    </main>
  );
}
