import {
  createElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ElementType,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// The app-wide styled tooltip — the single replacement for the browser's native
// `title=` bubble. It mirrors the scoreboard's .sb-term popover (theme tokens,
// same face + shape) so every hover hint reads as one system.
//
// Two design choices make it drop in anywhere the old `title` did:
//   • It renders the TRIGGER element itself (via `as`, default <span>) rather
//     than wrapping it, so it slots straight into grid/flex layouts where the
//     trigger is a direct child (table-head cells, the split-grid categories).
//   • The bubble is painted through a portal on <body> at position:fixed, so it
//     escapes every `overflow` scroll/clip ancestor (side panels, the detail
//     card, map chrome) that a pure-CSS absolute popover would be trapped in.
//
// Opens on hover AND keyboard focus; a non-interactive trigger becomes
// focusable (tabIndex 0) unless the caller pins tabIndex (e.g. -1 for a cell
// under an aria-hidden header). Consumer hover/focus handlers are composed, not
// clobbered — a DetailCard row drives its map hover off the same onMouseEnter.
// The anchor rect comes off the event's own currentTarget (no ref into render).
// Styles: `.tt` in index.css.

type Placement = "top" | "bottom" | "left" | "right";

type TooltipProps = {
  tip: ReactNode;
  placement?: Placement;
  as?: ElementType;
  children?: ReactNode;
} & Record<string, unknown>;

// Just the slice of the DOM event this component touches — the element the
// handler is bound to, which is exactly the trigger to anchor against.
type TriggerEvent = { currentTarget: Element };

export default function Tooltip({
  tip,
  placement = "top",
  as = "span",
  children,
  ...rest
}: TooltipProps) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const hide = useCallback(() => setRect(null), []);

  // While open, any scroll (in any ancestor scroller) or resize would strand the
  // fixed bubble away from its anchor — dismiss instead, matching how the native
  // title vanishes on scroll. Capture phase catches inner panel scrollers too.
  useEffect(() => {
    if (!rect) return;
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [rect, hide]);

  const hasTip = tip != null && tip !== "";

  const { onMouseEnter, onMouseLeave, onFocus, onBlur, tabIndex, ...others } =
    rest as Record<string, unknown>;

  const open = (e: TriggerEvent) => {
    if (e && e.currentTarget) setRect(e.currentTarget.getBoundingClientRect());
  };
  // Fire the consumer's own handler alongside ours, never in its place.
  const also = (fn: unknown, e: TriggerEvent) => {
    if (typeof fn === "function") (fn as (ev: TriggerEvent) => void)(e);
  };

  const triggerProps: Record<string, unknown> = {
    ...others,
    tabIndex: tabIndex !== undefined ? tabIndex : hasTip ? 0 : undefined,
    onMouseEnter: hasTip
      ? (e: TriggerEvent) => {
          also(onMouseEnter, e);
          open(e);
        }
      : onMouseEnter,
    onMouseLeave: hasTip
      ? (e: TriggerEvent) => {
          also(onMouseLeave, e);
          hide();
        }
      : onMouseLeave,
    onFocus: hasTip
      ? (e: TriggerEvent) => {
          also(onFocus, e);
          open(e);
        }
      : onFocus,
    onBlur: hasTip
      ? (e: TriggerEvent) => {
          also(onBlur, e);
          hide();
        }
      : onBlur,
  };

  return (
    <>
      {createElement(as, triggerProps, children)}
      {hasTip && rect
        ? createPortal(
            <TooltipBubble anchor={rect} placement={placement}>
              {tip}
            </TooltipBubble>,
            document.body
          )
        : null}
    </>
  );
}

// The floating bubble: measures itself, then positions against the trigger's
// viewport rect — flipping to the opposite side if the preferred edge would run
// off-screen, and clamping to stay fully in view. Hidden for the first paint so
// it never flashes at the pre-measured spot.
export function TooltipBubble({
  anchor,
  placement,
  children,
  className,
}: {
  anchor: DOMRect;
  placement: Placement;
  children: ReactNode;
  className?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const node = el.current;
    if (!node) return;
    const { width: w, height: h } = node.getBoundingClientRect();
    const gap = 6;
    const pad = 4;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cx = anchor.left + anchor.width / 2;
    const cy = anchor.top + anchor.height / 2;

    let place = placement;
    if (place === "top" && anchor.top - gap - h < pad) place = "bottom";
    else if (place === "bottom" && anchor.bottom + gap + h > vh - pad)
      place = "top";
    else if (place === "left" && anchor.left - gap - w < pad) place = "right";
    else if (place === "right" && anchor.right + gap + w > vw - pad)
      place = "left";

    let left: number;
    let top: number;
    switch (place) {
      case "bottom":
        left = cx - w / 2;
        top = anchor.bottom + gap;
        break;
      case "left":
        left = anchor.left - gap - w;
        top = cy - h / 2;
        break;
      case "right":
        left = anchor.right + gap;
        top = cy - h / 2;
        break;
      default:
        left = cx - w / 2;
        top = anchor.top - gap - h;
    }

    left = Math.max(pad, Math.min(left, vw - w - pad));
    top = Math.max(pad, Math.min(top, vh - h - pad));
    setPos({ left, top });
  }, [anchor, placement]);

  return (
    <div
      ref={el}
      role="tooltip"
      className={`tt${className ? ` ${className}` : ""}`}
      style={{
        left: pos ? pos.left : anchor.left,
        top: pos ? pos.top : anchor.top,
        visibility: pos ? "visible" : "hidden",
      }}
    >
      {children}
    </div>
  );
}
