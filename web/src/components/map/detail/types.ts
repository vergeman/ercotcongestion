// A hovered or pinned settlement point plus its forecast/realized decomposition,
// shared by DetailCard and its bodies. The decomposition is carried in every
// view so the error never hides raw magnitude: forecast / realized congestion,
// their difference (error = forecast − realized), and the realized DAM SPP.
export interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  spState: {
    predicted: number | null;
    market: number | null;
    error: number | null;
    marketSpp: number | null;
    predictedSpp: number | null;
  } | null;
}
