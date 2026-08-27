"use client";

import { useCallback, useEffect, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";

type Status = { ready: boolean; points_count: number };

export function RagStatusPanel({ activeTenantId }: { activeTenantId: string | null }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadStatus = useCallback(() => {
    if (!activeTenantId) return;
    apiFetch("/api/rag/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [activeTenantId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const generate = () => {
    setGenerating(true);
    setMessage(null);
    apiFetch("/api/rag/generate", { method: "POST" })
      .then((r) => r.json())
      .then((body) => {
        if (body.ok) {
          setMessage(`✓ ${body.chunks_indexed} chunks indexed`);
          loadStatus();
        } else {
          setMessage(`⚠ ${body.error ?? "generation failed"}`);
        }
      })
      .catch((err) => setMessage(`⚠ ${String(err)}`))
      .finally(() => setGenerating(false));
  };

  return (
    <Panel eyebrow="Index status" category="rag" collapsible={false}>
      <div className="flex items-center gap-2 text-xs">
        <span
          className={"h-1.5 w-1.5 rounded-full " + (status?.ready ? "bg-aegis-ok" : "bg-aegis-faint")}
        />
        <span className="text-aegis-dim">
          {status?.ready ? `${status.points_count} chunks indexed` : "empty index"}
        </span>
        <button
          type="button"
          onClick={generate}
          disabled={generating || !activeTenantId}
          className="ml-auto rounded border border-aegis-border px-2 py-0.5 text-[11px] text-aegis-text disabled:opacity-40"
        >
          {generating ? "Generating…" : "Generate"}
        </button>
      </div>
      {message && <span className="text-xs text-aegis-dim">{message}</span>}
    </Panel>
  );
}
