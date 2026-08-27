"use client";

import { useState, type ReactNode } from "react";

/**
 * Generic shell for the left (Settings) and right (RAG) sidebars —
 * collapsible to free up space for the chat area. Each sidebar's content is
 * still defined by the caller (see app/page.tsx).
 */
export function CollapsibleSidebar({
  side,
  title,
  children,
  defaultOpen = true,
}: {
  side: "left" | "right";
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const borderSide = side === "left" ? "border-r" : "border-l";

  if (!open) {
    return (
      <div className={`flex flex-shrink-0 flex-col items-center bg-aegis-surface-2 py-4 ${borderSide} border-aegis-border`}>
        <button
          type="button"
          onClick={() => setOpen(true)}
          title={`Open ${title}`}
          className="rounded-md p-1.5 text-sm text-aegis-faint hover:text-aegis-text"
        >
          {side === "left" ? "»" : "«"}
        </button>
      </div>
    );
  }

  return (
    <div
      className={`flex h-full min-h-0 w-72 flex-shrink-0 flex-col gap-3 overflow-y-auto bg-aegis-surface-2 px-4 py-6 ${borderSide} border-aegis-border`}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-aegis-dim">{title}</h2>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title="Collapse"
          className="rounded p-1 text-sm text-aegis-faint hover:text-aegis-text"
        >
          {side === "left" ? "«" : "»"}
        </button>
      </div>
      {children}
    </div>
  );
}
