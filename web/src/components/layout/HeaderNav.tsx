// Shared brand + primary nav, rendered identically on the map and scoreboard
// topbars so the two pages read as one product. `active` bolds the current
// section; `Analysis` is a placeholder for a not-yet-built page (disabled).

import Tooltip from "../ui/Tooltip";

type NavKey = "map" | "matrix" | "scoreboard" | "analysis";

const NAV: { key: NavKey; label: string; href?: string; newTab?: boolean }[] = [
  { key: "map", label: "Map", href: "/map" },
  { key: "matrix", label: "Matrix", href: "/matrix" },
  { key: "scoreboard", label: "Scoreboard", href: "/scoreboard" },
  { key: "analysis", label: "Analysis" }, // not yet built — disabled
];

export default function HeaderNav({
  active,
  onNavigate,
}: {
  active: NavKey;
  onNavigate?: (workspace: "map" | "matrix") => void;
}) {
  return (
    <div className="brand-nav">
      <span className="brand-nav__logo">⚡</span>
      <span className="brand-nav__title">ERCOT Stress</span>
      <nav className="brand-nav__links" aria-label="Primary">
        {NAV.map((n) =>
          n.href ? (
            <a
              key={n.key}
              href={n.href}
              target={n.newTab ? "_blank" : undefined}
              rel={n.newTab ? "noopener noreferrer" : undefined}
              onClick={(event) => {
                if (!onNavigate || (n.key !== "map" && n.key !== "matrix")) return;
                if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                onNavigate(n.key);
              }}
              className={`brand-nav__link${active === n.key ? " active" : ""}`}
              aria-current={active === n.key ? "page" : undefined}
            >
              {n.label}
            </a>
          ) : (
            <Tooltip
              key={n.key}
              placement="bottom"
              className="brand-nav__link brand-nav__link--disabled"
              aria-disabled="true"
              tip="Coming soon"
            >
              {n.label}
            </Tooltip>
          )
        )}
      </nav>

      <style>{`
        .brand-nav { display: flex; align-items: center; gap: 8px; }
        .brand-nav__logo { font-size: var(--fs-xl); }
        .brand-nav__title {
          font-family: var(--font-label);
          font-weight: 700;
          font-size: var(--fs-xl);
          letter-spacing: var(--track-title);
          text-transform: uppercase;
          color: var(--accent);
        }
        .brand-nav__links {
          display: flex;
          align-items: center;
          gap: 2px;
          margin-left: 14px;
        }
        .brand-nav__link {
          font-family: var(--font-label);
          font-weight: var(--fw-label);
          font-size: var(--fs-md);
          letter-spacing: var(--track-label);
          color: var(--text-secondary);
          text-decoration: none;
          padding: 4px 8px;
          border-radius: 3px;
        }
        .brand-nav__link:hover {
          color: var(--text-primary);
          background: var(--bg-hover);
        }
        .brand-nav__link.active { color: var(--accent); }
        .brand-nav__link--disabled { color: var(--text-muted); cursor: default; }
        .brand-nav__link--disabled:hover {
          color: var(--text-muted);
          background: none;
        }
        @media (max-width: 767px) {
          .brand-nav { min-width: 0; gap: 5px; }
          .brand-nav__logo { font-size: var(--fs-lg); }
          .brand-nav__title {
            font-size: var(--fs-lg);
            white-space: nowrap;
          }
          .brand-nav__links { display: none; }
        }
      `}</style>
    </div>
  );
}
