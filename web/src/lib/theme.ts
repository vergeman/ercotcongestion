// Theme state. The resolved theme lives as `data-theme` on <html>, which is what
// index.css switches on; everything else (component styles, map paint) reads
// from there so there is exactly one source of truth.
//
// Dark is the default rather than the OS preference: the app shipped dark, and
// the map's data palettes in lib/colors.ts are still anchored for a dark ground.

import { useEffect, useState } from "react";
import { APP_STORAGE_PREFIX } from "./brand";

export type Theme = "dark" | "light";

const STORAGE_KEY = `${APP_STORAGE_PREFIX}:theme`;

export const THEME_CHANGE_EVENT = `${APP_STORAGE_PREFIX}:themechange`;

export function readStoredTheme(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    // Private-mode / blocked storage — fall through to the default.
  }
  return "dark";
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

// Sets the attribute and notifies non-CSS consumers (the map, which paints via
// maplibre properties rather than stylesheets).
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Non-fatal: the theme still applies for this session.
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "light" ? "dark" : "light";
  applyTheme(next);
  return next;
}

// Subscribe to theme changes. Returns an unsubscribe fn.
export function onThemeChange(fn: (t: Theme) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<Theme>).detail);
  window.addEventListener(THEME_CHANGE_EVENT, handler);
  return () => window.removeEventListener(THEME_CHANGE_EVENT, handler);
}

// Resolve a CSS custom property to a concrete value. The map needs real color
// strings for maplibre paint properties, which cannot take var().
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}

// Re-render a component when the theme flips.
//
// Needed by SVG that colors itself through *presentation attributes*
// (`fill="…"` / `stroke="…"`). Those cannot take var(), and moving them to the
// `style` prop is not a safe substitute: an inline style outranks a stylesheet
// rule, so it would silently override rules like `.ov-iso .ov-core { stroke }`
// that are meant to win. Re-resolving the token via cssVar() on each render
// keeps the existing cascade intact.
export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  useEffect(() => onThemeChange(setTheme), []);
  return theme;
}
