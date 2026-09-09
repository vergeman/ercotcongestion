// The four charted sources, in fixed identity order, colored from the dataviz
// reference palette's dark categorical slots 1–4 (validated on the panel
// surface). The first four sit at the CVD floor, so the required secondary
// encoding ships too: a legend + direct end-labels on every line.
export const SERIES = [
  { seriesId: "model", color: "#3987e5" },
  { seriesId: "persistence", color: "#008300" },
  { seriesId: "climatology", color: "#d55181" },
  { seriesId: "oracle", color: "#c98500" },
] as const;

export const CHART_LABELS: Record<string, string> = {
  model: "Model",
  persistence: "Persistence",
  climatology: "Baseline",
  oracle: "Oracle",
};
