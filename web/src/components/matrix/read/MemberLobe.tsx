import type { ReachSp } from "../../../api/types";
import { shiftFactorColor } from "../../../lib/colors";

const LOBE_VISIBLE = 8;

function MemberRow({ sp }: { sp: ReachSp }) {
  return (
    <li className="cr-mem-row">
      <span
        className="cr-dot"
        style={{ background: shiftFactorColor(sp.sf) }}
      />
      <span className="cr-mem-sp mono">{sp.settlement_point}</span>
      <span
        className="cr-mem-sf mono"
        style={{ color: shiftFactorColor(sp.sf) }}
      >
        {sp.sf.toFixed(3)}
      </span>
    </li>
  );
}

// One end of a constraint's reach — its located member nodes. The first
// LOBE_VISIBLE show; the rest fold into a disclosure.
export function MemberLobe({ title, members }: { title: string; members: ReachSp[] }) {
  const visible = members.slice(0, LOBE_VISIBLE);
  const rest = members.slice(LOBE_VISIBLE);
  return (
    <div className="mrd-lobe">
      <h4>
        {title} <em>{members.length}</em>
      </h4>
      {visible.length === 0 ? (
        <div className="cr-mem-msg">none located</div>
      ) : (
        <ul className="cr-mem" role="list">
          {visible.map((sp) => (
            <MemberRow key={sp.settlement_point} sp={sp} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <details className="mrd-lobe__tail">
          <summary>{rest.length} more</summary>
          <ul className="cr-mem" role="list">
            {rest.map((sp) => (
              <MemberRow key={sp.settlement_point} sp={sp} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
