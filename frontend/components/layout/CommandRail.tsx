"use client";

import { useState, type ReactNode } from "react";

/**
 * The single left rail — merges what used to be two flanking sidebars
 * (Settings, RAG) into one collapsible rail with a Settings/RAG tab switch.
 * StatusStrip (above this, in app/page.tsx) carries the always-visible
 * glanceable recap, so collapsing this rail doesn't lose sight of the
 * current tenant/model/safety/RAG state — only the controls to change them.
 */
export function CommandRail({
  settingsContent,
  ragContent,
}: {
  settingsContent: ReactNode;
  ragContent: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState<"settings" | "rag">("settings");

  if (!open) {
    return (
      <div className="flex flex-shrink-0 flex-col items-center border-r border-aegis-border bg-aegis-surface-2 py-4">
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Open"
          className="rounded-md p-1.5 text-sm text-aegis-faint hover:text-aegis-text"
        >
          »
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-72 flex-shrink-0 flex-col border-r border-aegis-border bg-aegis-surface-2">
      <div className="flex flex-shrink-0 items-center border-b border-aegis-border">
        <button
          type="button"
          onClick={() => setTab("settings")}
          className={
            "flex-1 border-b-2 py-2.5 text-xs font-bold uppercase tracking-wide " +
            (tab === "settings" ? "border-aegis-accent text-aegis-text" : "border-transparent text-aegis-dim")
          }
        >
          ⚙️ Settings
        </button>
        <button
          type="button"
          onClick={() => setTab("rag")}
          className={
            "flex-1 border-b-2 py-2.5 text-xs font-bold uppercase tracking-wide " +
            (tab === "rag" ? "border-aegis-accent text-aegis-text" : "border-transparent text-aegis-dim")
          }
        >
          📚 RAG
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title="Collapse"
          className="flex-none border-l border-aegis-border px-2.5 py-2.5 text-aegis-faint hover:text-aegis-text"
        >
          «
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {tab === "settings" ? settingsContent : ragContent}
      </div>
    </div>
  );
}
