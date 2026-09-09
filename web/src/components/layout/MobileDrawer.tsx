import { useRef, type ReactNode } from "react";
import { useModalDismiss } from "../../hooks/useModalDismiss";

interface Props {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

// The mobile drawer owns the app's secondary controls. It intentionally stays
// mounted only while open: this keeps its focus boundary small and prevents the
// desktop-only sidebar from being announced twice by screen readers.
export default function MobileDrawer({ open, onClose, children }: Props) {
  const panelRef = useRef<HTMLElement>(null);

  useModalDismiss({
    open,
    onClose,
    panelRef,
    initialFocus: "[data-drawer-close]",
    trapFocus: true,
  });

  if (!open) return null;

  return (
    <div className="mobile-drawer" role="presentation">
      <button
        className="mobile-drawer__backdrop"
        aria-label="Close menu"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        className="mobile-drawer__panel"
        role="dialog"
        aria-modal="true"
        aria-label="Map controls and information"
      >
        <div className="mobile-drawer__header">
          <span className="mobile-drawer__title">Map controls</span>
          <button data-drawer-close onClick={onClose} aria-label="Close menu">
            ✕
          </button>
        </div>
        <div className="mobile-drawer__content">{children}</div>
      </aside>

      <style>{`
        .mobile-drawer {
          position: fixed;
          inset: 0;
          z-index: 80;
          display: flex;
          justify-content: flex-end;
        }
        .mobile-drawer__backdrop {
          position: absolute;
          inset: 0;
          border: 0;
          border-radius: 0;
          padding: 0;
          background: rgba(0, 0, 0, 0.52);
        }
        .mobile-drawer__panel {
          position: relative;
          width: min(92vw, 390px);
          height: 100%;
          display: flex;
          flex-direction: column;
          background: var(--bg-panel);
          border-left: 1px solid var(--border-bright);
          box-shadow: var(--shadow-panel);
        }
        .mobile-drawer__header {
          min-height: var(--mobile-header-h);
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 max(12px, env(safe-area-inset-right)) 0 16px;
          border-bottom: 1px solid var(--border);
        }
        .mobile-drawer__title {
          color: var(--text-primary);
          font-family: var(--font-label);
          font-weight: 600;
          font-size: var(--fs-md);
        }
        .mobile-drawer__header button {
          width: 36px;
          height: 36px;
          padding: 0;
          font-size: 16px;
        }
        .mobile-drawer__content {
          flex: 1;
          min-height: 0;
          overflow-y: auto;
          overscroll-behavior: contain;
          padding: 14px 14px max(14px, env(safe-area-inset-bottom));
        }
      `}</style>
    </div>
  );
}
