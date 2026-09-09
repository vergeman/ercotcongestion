import { useEffect, type RefObject } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface Options {
  open: boolean;
  onClose: () => void;
  panelRef: RefObject<HTMLElement | null>;
  // Selector for the control to focus when the modal opens (e.g. its close button).
  initialFocus?: string;
  // Keep Tab focus cycling within the panel while open.
  trapFocus?: boolean;
  // Freeze page scroll behind the modal while open.
  lockScroll?: boolean;
}

// Escape-to-close for a modal surface, with optional focus handling: focus a
// control on open, trap Tab within the panel, and return focus to the trigger
// on close.
export function useModalDismiss({
  open,
  onClose,
  panelRef,
  initialFocus,
  trapFocus = false,
  lockScroll = false,
}: Options) {
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    if (initialFocus) {
      const target = panel?.querySelector<HTMLElement>(initialFocus);
      requestAnimationFrame(() => target?.focus());
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (!trapFocus || event.key !== "Tab") return;
      const targets =
        panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ??
        ([] as unknown as NodeListOf<HTMLElement>);
      if (targets.length === 0) {
        event.preventDefault();
        return;
      }
      const first = targets[0];
      const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);

    let previousOverflow = "";
    if (lockScroll) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (lockScroll) document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [open, onClose, panelRef, initialFocus, trapFocus, lockScroll]);
}
