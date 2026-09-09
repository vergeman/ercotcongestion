import { fmtSf } from "../../../lib/format";
import { shiftFactorColor } from "../../../lib/colors";

// The colored block identifies the constraint's structural type. SF already has
// an explicit signed numeric column, so encoding its sign in the block was
// redundant and made type harder to scan.
const TYPE_TOKENS: Record<string, string> = {
  gtc: "--sf-gtc",
  transmission: "--sf-transmission",
  radial: "--sf-radial",
};

export function TypeChip({ ctype }: { ctype?: string | null }) {
  return (
    <span
      className="dc-chip"
      style={{
        background: `var(${TYPE_TOKENS[ctype ?? ""] ?? "--sf-untyped"})`,
      }}
      aria-hidden="true"
    />
  );
}

// Settlement points use their own nodal identifier, regardless of which
// constraint is currently being explored.
export function NodeChip() {
  return (
    <span
      className="dc-chip"
      style={{ background: "var(--violet)" }}
      aria-hidden="true"
    />
  );
}

// The signed, colored value carries the direction on its own; a separate dot
// beside it said the same thing twice and cost a grid column.
export function SfSign({ sf }: { sf: number }) {
  return (
    <span className="dc-driver-sf mono" style={{ color: shiftFactorColor(sf) }}>
      {fmtSf(sf)}
    </span>
  );
}
