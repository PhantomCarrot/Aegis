"use client";

import { useState, type ReactNode } from "react";

const CATEGORY_VAR = {
  settings: "var(--aegis-cat-settings)",
  rag: "var(--aegis-cat-rag)",
  tenants: "var(--aegis-cat-tenants)",
} as const;

export type PanelCategory = keyof typeof CATEGORY_VAR;

/**
 * The shared sidebar building block — every entry under Settings/RAG is one
 * of these: an eyebrow label, an optional category color (the left-border
 * strip that groups Settings/RAG/Tenants entries at a glance), and either
 * static content (Model, Safety — collapsible={false}) or a disclosure
 * (Tools, Config, Tenants, Documents — the default).
 */
export function Panel({
  eyebrow,
  category,
  collapsible = true,
  defaultOpen = true,
  headerRight,
  onOpen,
  children,
}: {
  eyebrow: string;
  category?: PanelCategory;
  collapsible?: boolean;
  defaultOpen?: boolean;
  /** Non-interactive content next to the chevron — a count, a status dot. */
  headerRight?: ReactNode;
  /** Fires on every closed→open transition — for lazy-fetching content.
   * Pair with the caller's own "already loaded?" check (its data state is
   * null) so it's a no-op once loaded, same as fetching on mount would be. */
  onOpen?: () => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = !collapsible || open;

  const handleToggle = () => {
    const next = !open;
    setOpen(next);
    if (next) onOpen?.();
  };

  const header = (
    <>
      <span className="text-[10.5px] font-bold uppercase tracking-wider text-aegis-dim">{eyebrow}</span>
      <div className="flex items-center gap-2">
        {headerRight}
        {collapsible && <Chevron open={open} />}
      </div>
    </>
  );

  return (
    <div
      className="flex flex-col gap-2.5 rounded-lg border border-aegis-border bg-aegis-surface p-3"
      style={category ? { borderLeftWidth: 3, borderLeftColor: CATEGORY_VAR[category] } : undefined}
    >
      {collapsible ? (
        <button type="button" onClick={handleToggle} className="flex items-center justify-between">
          {header}
        </button>
      ) : (
        <div className="flex items-center justify-between">{header}</div>
      )}
      {isOpen && <div className="flex flex-col gap-2.5">{children}</div>}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
      className={
        "h-3 w-3 flex-none text-aegis-faint transition-transform duration-150 " + (open ? "" : "-rotate-90")
      }
    >
      <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
