import { useMemo } from "react";
import { cssVar } from "../../lib/theme";
import { shiftFactorColor } from "../../lib/colors";
import type { OvMember } from "./overviewSources";

// The multi-constraint hover box (plan/0112). A plain positioned <div> anchored
// at the hovered node's pixel position — no SVG. Opened by the base `sps` hover
// when a node belongs to 2+ overview constraints; each row previews that
// constraint in the DetailCard on hover and pins it on click.
const SF_TOKENS: Record<string, string> = {
  gtc: "--sf-gtc",
  transmission: "--sf-transmission",
  radial: "--sf-radial",
};

interface Props {
  name: string;
  kind: "node" | "gtc" | "transmission";
  members?: OvMember[];
  meta?: string | null;
  x: number;
  y: number;
  containerWidth: number;
  onRowHover?: (key: string | null) => void;
  onRowClick?: (key: string) => void;
  onLeave: () => void;
}

export default function OverviewPopover({
  name,
  kind,
  members,
  meta,
  x,
  y,
  containerWidth,
  onRowHover,
  onRowClick,
  onLeave,
}: Props) {
  const colors = useMemo(() => {
    const byType: Record<string, string> = {};
    for (const [k, tok] of Object.entries(SF_TOKENS)) byType[k] = cssVar(tok);
    return { byType, untyped: cssVar("--sf-untyped") };
  }, []);

  const flip = x > containerWidth - 300;
  const left = flip ? x - 300 : x + 12;
  const top = y + 12;
  const shown = members?.slice(0, 10) ?? [];
  const hasMembers = shown.length > 0;
  const typeToken =
    kind === "gtc" ? "--sf-gtc" : kind === "transmission" ? "--sf-transmission" : "--violet";

  return (
    <div
      className={`ov-pop${hasMembers ? "" : " ov-pop--static"}`}
      style={{ left, top }}
      onMouseLeave={onLeave}
    >
      <div className={`ov-pop-sp${hasMembers ? "" : " ov-pop-sp--solo"}`}>
        <span className="ov-chip ov-pop-sp__chip" style={{ background: `var(${typeToken})` }} />
        <span>{name}</span>
        <small>
          · {hasMembers ? `${members!.length} constraint${members!.length > 1 ? "s" : ""}` : kind === "gtc" ? "GTC" : kind === "transmission" ? "Transmission" : "node"}
        </small>
      </div>
      {meta && <div className="ov-pop-meta">{meta}</div>}
      {shown.map((m) => {
        const imp = m.sf < 0;
        return (
          <div
            key={m.key}
            className="ov-row"
            onMouseEnter={() => onRowHover?.(m.key)}
            onClick={() => onRowClick?.(m.key)}
          >
            <span className="ov-chip" style={{ background: colors.byType[m.type] ?? colors.untyped }} />
            <span className="ov-ck">{m.key}</span>
            <span className="ov-role" style={{ color: shiftFactorColor(m.sf) }}>
              {imp ? "import" : "export"} {m.sf.toFixed(2)}
            </span>
            <span className="ov-bh">{m.bh ?? "—"}h</span>
          </div>
        );
      })}
      {(members?.length ?? 0) > 10 && (
        <div className="ov-more">+{members!.length - 10} more</div>
      )}
      <style>{`
        .ov-pop { position: absolute; pointer-events: auto; background: var(--bg-glass);
          border: 1px solid var(--border); border-radius: 7px; padding: 6px; font-size: var(--fs-body);
          min-width: 210px; max-width: 290px; box-shadow: var(--shadow-panel); z-index: 5; }
        .ov-pop--static { pointer-events: none; min-width: 0; }
        .ov-pop-sp { display: flex; align-items: center; gap: 7px; font-family: var(--font-mono);
          font-weight: 600; font-size: var(--fs-body); padding: 2px 5px 6px; color: var(--text-primary);
          border-bottom: 1px solid var(--border); margin-bottom: 4px; }
        .ov-pop-sp--solo { padding-bottom: 2px; border-bottom: none; margin-bottom: 0; }
        .ov-pop-sp__chip { width: 8px; height: 8px; }
        .ov-pop-sp small { color: var(--text-secondary); font-weight: 400; }
        .ov-pop-meta { margin: 3px 5px 1px 20px; color: var(--text-secondary);
          font-size: var(--fs-label); }
        .ov-row { display: flex; align-items: center; gap: 7px; padding: 4px 5px;
          border-radius: 4px; cursor: pointer; }
        .ov-row:hover { background: var(--bg-hover); }
        .ov-chip { width: 8px; height: 8px; border-radius: 2px; flex: 0 0 auto; }
        .ov-ck { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          font-family: var(--font-mono); font-size: var(--fs-label); }
        .ov-role { font-weight: 700; font-size: var(--fs-label); }
        .ov-bh { color: var(--text-secondary); font-size: var(--fs-label); width: 34px; text-align: right; }
        .ov-more { color: var(--text-secondary); font-size: var(--fs-label); text-align: center; padding: 3px; }
      `}</style>
    </div>
  );
}
