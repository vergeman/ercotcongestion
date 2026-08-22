export const MATRIX_COPY = {
  eyebrow: "Explorer / matrix",
  title: "Constraint × settlement point",
  waitingForPlayback: "Waiting for playback data",
  loadingFrame: "Loading matrix frame…",
  loadingDetail: "Loading detail…",
  loadErrorTitle: "Unable to load Matrix",
  retry: "Retry",
  unavailableTitle: "Matrix unavailable for this hour",
  missingArtifact:
    "No causal daily Matrix artifact was published for this delivery day.",
  outOfRange: "This timestamp is outside the available Matrix artifact.",
  emptyTitle: "No bounded Matrix values",
  emptyDescription:
    "The selected artifact contains no rows or settlement-point columns for this bounded view.",
  waitingTitle: "Waiting for a playback hour",
  waitingDescription:
    "Choose an available timestamp in the shared playback scrubber to load its Matrix frame.",
  lens: { label: "Lens", detail: "Detail", sf: "SF", basis: "Basis" },
  value: {
    label: "Value",
    data: "Data",
    shiftFactor: "Shift Factor",
    forecastMu: "Forecast μ",
    damMu: "ERCOT DAM μ",
  },
  basisUnavailable:
    "Basis is available only on the Nodes tab because it compares two settlement points.",
  basisSource: "Basis μ source",
  updatingFrame: "Updating frame…",
  pendingDam:
    "No ERCOT DAM μ values matched the displayed constraints for this hour.",
  run: (runId: string) => `Run ${runId}`,
  deliveryDay: (day: string) => `Delivery day ${day}`,
  constraintCount: (shown: number, total: number) =>
    `${shown} of ${total} constraints`,
  settlementPointCount: (shown: number, total: number) =>
    `${shown} of ${total} settlement points`,
  partialDam: (matched: number, total: number) =>
    `DAM μ: ${matched}/${total} constraints matched; unmatched cells are unavailable.`,
};
