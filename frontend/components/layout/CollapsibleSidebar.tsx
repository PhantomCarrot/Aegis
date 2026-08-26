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
      <div className={`flex flex-shrink-0 flex-col items-center py-4 ${borderSide} border-black/10 dark:border-white/10`}>
        <button
          type="button"
          onClick={() => setOpen(true)}
          title={`Open ${title}`}
          className="rounded-md p-1.5 text-sm text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
        >
          {side === "left" ? "»" : "«"}
        </button>
      </div>
    );
  }

  return (
    <div
      className={`flex h-full min-h-0 w-72 flex-shrink-0 flex-col gap-5 overflow-y-auto px-4 py-6 ${borderSide} border-black/10 dark:border-white/10`}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {title}
        </h2>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title="Collapse"
          className="rounded p-1 text-sm text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
        >
          {side === "left" ? "«" : "»"}
        </button>
      </div>
      {children}
    </div>
  );
}
