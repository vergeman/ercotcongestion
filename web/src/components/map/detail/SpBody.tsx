import { fmt, fmtCong } from "../../../lib/format";
import { Row } from "./Row";
import type { HoveredSp } from "./types";

// The pinned/hovered node's forecast, realized, and error congestion plus both
// LMPs. The side the card is scoped to reads solid; the other is dimmed.
export function SpBody({
  sp,
  valueMode,
}: {
  sp: HoveredSp;
  valueMode: "forecast" | "ercot";
}) {
  const s = sp.spState;
  const forecastMode = valueMode === "forecast";
  return (
    <>
      <Row label="SP Type" value={String(sp.props.sp_type ?? "—")} />
      <Row label="Load Zone" value={String(sp.props.load_zone ?? "—")} />
      <Row
        label="Forecast Congestion"
        value={fmtCong(s?.predicted)}
        deemphasized={!forecastMode}
      />
      <Row
        label="Realized Congestion"
        value={fmtCong(s?.market)}
        deemphasized={forecastMode}
      />
      <Row
        label="Forecast Error"
        value={fmtCong(s?.error)}
        deemphasized={!forecastMode}
      />
      <Row
        label="Predicted LMP"
        value={
          s && s.predictedSpp != null ? `$${fmt(s.predictedSpp, 2)}/MWh` : null
        }
        deemphasized={!forecastMode}
      />
      <Row
        label="DAM LMP"
        value={s && s.marketSpp != null ? `$${fmt(s.marketSpp, 2)}/MWh` : null}
        deemphasized={forecastMode}
      />
    </>
  );
}
