"use client";

import { useEffect, useState, type ReactNode } from "react";

import { SAFETY_MODE_LABEL, type SafetyMode } from "@/components/chat/SafetyModeBadge";
import { apiFetch } from "@/lib/api";

type ExecInfo = { mode: "local" | "ssh" };
type RagStatus = { ready: boolean; points_count: number };

/**
 * Always-visible glanceable recap — tenant, model, safety, exec target, RAG
 * index — sitting between the header and the command rail so the current
 * state stays visible even with the rail collapsed. Fetches exec/RAG info
 * itself (same endpoints ConfigPanel/RagStatusPanel already use) rather
 * than lifting their state, matching this app's convention of each panel
 * owning its own fetch.
 */
export function StatusStrip({
  activeTenantId,
  tenantName,
  connected,
  model,
  safetyMode,
}: {
  activeTenantId: string | null;
  tenantName: string | null;
  connected: boolean;
  model: string | null;
  safetyMode: SafetyMode;
}) {
  const [exec, setExec] = useState<ExecInfo | null>(null);
  const [rag, setRag] = useState<RagStatus | null>(null);

  useEffect(() => {
    if (!activeTenantId) return;
    apiFetch("/api/tenants/config")
      .then((r) => r.json())
      .then((body) => setExec(body.exec))
      .catch(() => setExec(null));
    apiFetch("/api/rag/status")
      .then((r) => r.json())
      .then(setRag)
      .catch(() => setRag(null));
  }, [activeTenantId]);

  return (
    <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-aegis-border bg-aegis-surface-2 px-5 py-2 text-xs">
      <Stat>
        <span className={"h-1.5 w-1.5 rounded-full " + (connected ? "bg-aegis-ok" : "bg-aegis-faint")} />
        <b>{tenantName ?? "—"}</b>
      </Stat>
      <Stat>
        Model: <b className="font-mono">{model ?? "—"}</b>
      </Stat>
      <Stat>
        Safety: <b>{SAFETY_MODE_LABEL[safetyMode]}</b>
      </Stat>
      <Stat>
        Exec: <b>{exec?.mode ?? "…"}</b>
      </Stat>
      <Stat>
        <span className="h-1.5 w-1.5 rounded-full bg-aegis-cat-rag" />
        RAG: <b>{rag ? `${rag.points_count} chunks` : "…"}</b>
      </Stat>
    </div>
  );
}

function Stat({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-aegis-border bg-aegis-surface px-2.5 py-1 text-aegis-dim">
      {children}
    </div>
  );
}
