"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";

export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "aegis:theme";

function getSnapshot(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

// Matches the inline script's own fallback reasoning closely enough to
// avoid a jarring mismatch; useSyncExternalStore re-syncs to the real
// client snapshot immediately after hydration on its own, no effect needed.
function getServerSnapshot(): Theme {
  return "dark";
}

function subscribe(callback: () => void): () => void {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

type ThemeContextValue = { theme: Theme; toggleTheme: () => void };

// No default value, same reasoning as useTenant(): calling this outside the
// provider is a programming error, not a state to handle gracefully.
const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Light ("Daylight Ops") / dark ("Slate Console") — see app/globals.css for
 * the token values. The actual class on <html> is set synchronously by an
 * inline script in layout.tsx *before* this provider ever mounts, to avoid
 * a flash of the wrong theme. `theme` here is read straight from that class
 * via useSyncExternalStore (the React-blessed way to subscribe to external,
 * non-React-owned state like the DOM) rather than mirrored into its own
 * setState — toggling just mutates the class directly and the subscription
 * picks it up.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  };

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme() must be used inside a <ThemeProvider>.");
  }
  return ctx;
}
