// Shared brand + primary nav, rendered identically across the map, matrix,
// scoreboard, and analysis topbars so they read as one product. `active` bolds
// the current section. Links route client-side through the Router (no reload);
// Scoreboard is the deliberate full-reload exception (see NAV `reload`).

import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { APP_TITLE } from "../../lib/brand";
import Tooltip from "../ui/Tooltip";

type NavKey = "map" | "matrix" | "scoreboard" | "brief" | "analysis" | "about";

// `reload: true` opts a destination out of client-side routing — its link does a
// full-page load instead. Everything else routes through the Router (no reload).
// Scoreboard is the deliberate exception.
const NAV: { key: NavKey; label: string; href?: string; newTab?: boolean; reload?: boolean }[] = [
  { key: "brief", label: "Brief", href: "/" },
  { key: "map", label: "Map", href: "/map" },
  { key: "matrix", label: "Matrix", href: "/matrix" },
  { key: "scoreboard", label: "Scoreboard", href: "/scoreboard", reload: true },
  { key: "about", label: "About", href: "/about" },
];

export default function HeaderNav({
  active,
  onNavigate,
}: {
  active: NavKey;
  onNavigate?: (workspace: "map" | "matrix") => void;
}) {
  const navigate = useNavigate();
  const { search } = useLocation();
  // Carry only the shared time coordinate (t / run / span) across sections, so
  // "when" stays consistent between Map, Matrix, and Analysis. Page-local state
  // (selection, date) stays behind.
  const coord = useMemo(() => {
    const src = new URLSearchParams(search);
    const out = new URLSearchParams();
    for (const k of ["t", "run", "span", "ws", "we"]) {
      const v = src.get(k);
      if (v) out.set(k, v);
    }
    const s = out.toString();
    return s ? `?${s}` : "";
  }, [search]);
  return (
    <div className="brand-nav">
      <a
        className="brand-nav__brand"
        href="/"
        aria-label={`${APP_TITLE} home`}
        onClick={(event) => {
          // The brand is a home link, so it deliberately drops every page-local
          // and shared query parameter instead of using the nav coordinate.
          if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          navigate({ pathname: "/", search: "" });
        }}
      >
        <span className="brand-nav__logo">⚡</span>
        <span className="brand-nav__title">{APP_TITLE}</span>
      </a>
      <nav className="brand-nav__links" aria-label="Primary">
        {NAV.map((n) =>
          n.href ? (
            <a
              key={n.key}
              href={n.reload ? n.href : `${n.href}${coord}`}
              target={n.newTab ? "_blank" : undefined}
              rel={n.newTab ? "noopener noreferrer" : undefined}
              onClick={(event) => {
                // Let the browser handle modified / non-primary clicks (new tab,
                // new window) and the reload-opt-out destination (Scoreboard).
                if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                if (n.reload || !n.href) return;
                event.preventDefault();
                // Map/Matrix share the App shell; when it supplies onNavigate,
                // route through it so the current query (selection / discovery)
                // survives the workspace switch. Everything else routes plainly.
                if (onNavigate && (n.key === "map" || n.key === "matrix")) {
                  onNavigate(n.key);
                } else {
                  navigate({ pathname: n.href, search: coord });
                }
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
        .brand-nav__brand {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          color: inherit;
          text-decoration: none;
          border-radius: 3px;
        }
        .brand-nav__brand:focus-visible {
          outline: 2px solid var(--accent);
          outline-offset: 3px;
        }
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
          .brand-nav__brand { gap: 5px; }
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
