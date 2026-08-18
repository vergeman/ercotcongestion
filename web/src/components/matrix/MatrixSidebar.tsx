import type { MatrixTab } from "../../lib/matrix";

// One row in the sidebar list — already filtered/sorted by MatrixWorkspace,
// which owns the full constraint/node vocabulary this is drawn from.
export interface MatrixSidebarItem {
  id: string;
  label: string;
  sub: string | null;
  type: string | null;
  zone: string | null;
  sizeLabel: string | null;
  pinned: boolean;
}

interface Props {
  tab: MatrixTab;
  items: MatrixSidebarItem[];
  totalCount: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onTab: (tab: MatrixTab) => void;
  query: string;
  onQuery: (query: string) => void;
  fType: string;
  fZone: string;
  typeOptions: string[];
  zoneOptions: string[];
  onFilter: (next: { fType?: string; fZone?: string }) => void;
  onTogglePin: (id: string) => void;
  onReset: () => void;
}

function typeTag(type: string | null): string {
  if (!type) return "";
  if (type === "load_zone") return "LZ";
  if (type === "gtc") return "GTC";
  return type.toUpperCase().slice(0, 4);
}

export default function MatrixSidebar({
  tab, items, totalCount, selectedId, onSelect, onTab,
  query, onQuery, fType, fZone, typeOptions, zoneOptions, onFilter,
  onTogglePin, onReset,
}: Props) {
  return (
    <aside className="matrix-sidebar" aria-label="Matrix index">
      <div className="matrix-sidebar__tabs" role="tablist" aria-label="Index">
        <button type="button" role="tab" aria-selected={tab === "constraints"} className={tab === "constraints" ? "is-active" : ""} onClick={() => onTab("constraints")}>Constraints</button>
        <button type="button" role="tab" aria-selected={tab === "nodes"} className={tab === "nodes" ? "is-active" : ""} onClick={() => onTab("nodes")}>Nodes</button>
      </div>
      <div className="matrix-sidebar__filters">
        <input
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value.slice(0, 64))}
          placeholder={tab === "constraints" ? "Search name or contingency" : "Search settlement point"}
          aria-label="Search"
        />
        <select value={fType} onChange={(event) => onFilter({ fType: event.target.value })} aria-label="Filter by type">
          <option value="">All types</option>
          {typeOptions.map((type) => <option key={type} value={type}>{typeTag(type)}</option>)}
        </select>
        <select value={fZone} onChange={(event) => onFilter({ fZone: event.target.value })} aria-label="Filter by zone">
          <option value="">All zones</option>
          {zoneOptions.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
        </select>
      </div>
      <div className="matrix-sidebar__count">
        <span>{items.length} of {totalCount} {tab}</span>
        <button type="button" onClick={onReset}>Reset</button>
      </div>
      <div className="matrix-sidebar__list" role="listbox" aria-label={tab === "constraints" ? "Constraints" : "Settlement points"}>
        {items.length === 0 && <p className="matrix-sidebar__empty">No {tab} match this search.</p>}
        {items.map((item) => {
          // Constraints: the contingency (item.sub) differentiates otherwise
          // duplicate monitored-element names — shown as a grey subline under
          // the name, with the zone. The Σμ size sits in the aligned value
          // column. Nodes carry no contingency; their zone fills that column.
          const subline = tab === "constraints"
            ? [item.zone, item.sub].filter(Boolean).join(" · ")
            : "";
          const value = tab === "constraints" ? item.sizeLabel : item.zone;
          return (
            <div
              key={item.id}
              role="option"
              aria-selected={item.id === selectedId}
              className={`matrix-sidebar__row${item.id === selectedId ? " is-selected" : ""}`}
              tabIndex={0}
              onClick={() => onSelect(item.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(item.id); }
              }}
            >
              <button
                type="button"
                className={`matrix-sidebar__pin${item.pinned ? " is-pinned" : ""}`}
                aria-label={item.pinned ? `Unpin ${item.id}` : `Pin ${item.id}`}
                title={item.pinned ? "Unpin" : "Pin"}
                onClick={(event) => { event.stopPropagation(); onTogglePin(item.id); }}
              >
                {item.pinned ? "★" : "☆"}
              </button>
              <span className="matrix-sidebar__namecell">
                <span className="matrix-sidebar__name">{item.label}</span>
                {subline && <span className="matrix-sidebar__sub">{subline}</span>}
              </span>
              <span className="matrix-sidebar__tag-col">
                {item.type && <span className="matrix-sidebar__tag">{typeTag(item.type)}</span>}
              </span>
              <span className="matrix-sidebar__value">{value ?? "—"}</span>
            </div>
          );
        })}
      </div>
      <style>{`
        .matrix-sidebar { display: flex; flex-direction: column; min-height: 0; width: 340px; flex: 0 0 340px; background: var(--bg-panel); border: 1px solid var(--border); border-right: 0; }
        .matrix-sidebar__tabs { display: flex; border-bottom: 1px solid var(--border); }
        .matrix-sidebar__tabs button { flex: 1; border: 0; border-right: 1px solid var(--border); background: var(--bg-surface); color: var(--text-secondary); font: 600 var(--fs-label) var(--font-sans); padding: 8px; cursor: pointer; }
        .matrix-sidebar__tabs button:last-child { border-right: 0; }
        .matrix-sidebar__tabs button.is-active { background: var(--accent-dim); color: var(--accent); }
        .matrix-sidebar__filters { display: flex; flex-direction: column; gap: 6px; padding: 8px; border-bottom: 1px solid var(--border); }
        .matrix-sidebar__filters input, .matrix-sidebar__filters select { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); font: var(--fs-label) var(--font-sans); min-height: 30px; padding: 4px 6px; width: 100%; }
        .matrix-sidebar__count { align-items: center; color: var(--text-secondary); display: flex; font-size: var(--fs-micro); justify-content: space-between; padding: 6px 8px; border-bottom: 1px solid var(--border); }
        .matrix-sidebar__count button { background: transparent; border: 0; color: var(--text-secondary); cursor: pointer; font: 500 var(--fs-micro) var(--font-sans); padding: 2px 4px; }
        .matrix-sidebar__count button:hover { color: var(--accent); }
        .matrix-sidebar__list { flex: 1; min-height: 0; overflow: auto; }
        .matrix-sidebar__empty { color: var(--text-muted); padding: 12px; }
        .matrix-sidebar__row { align-items: center; border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent); cursor: pointer; display: grid; grid-template-columns: 18px minmax(0, 1fr) 46px 68px; column-gap: 8px; font-size: var(--fs-label); padding: 7px 10px; }
        .matrix-sidebar__row:hover { background: var(--bg-surface); }
        .matrix-sidebar__row.is-selected { background: var(--accent-dim); box-shadow: inset 3px 0 var(--accent); }
        .matrix-sidebar__pin { background: transparent; border: 0; color: var(--text-muted); cursor: pointer; font-size: var(--fs-label); padding: 0; text-align: center; }
        .matrix-sidebar__pin.is-pinned { color: var(--accent); }
        .matrix-sidebar__namecell { display: flex; flex-direction: column; min-width: 0; gap: 1px; }
        .matrix-sidebar__name { font-family: var(--font-mono); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
        .matrix-sidebar__sub { color: var(--text-muted); font-size: var(--fs-micro); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .matrix-sidebar__tag-col { display: flex; justify-content: flex-start; }
        .matrix-sidebar__tag { border: 1px solid var(--border); border-radius: 3px; color: var(--text-muted); font-size: 9.5px; letter-spacing: .04em; padding: 0 4px; text-transform: uppercase; white-space: nowrap; }
        .matrix-sidebar__value { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-micro); text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      `}</style>
    </aside>
  );
}
