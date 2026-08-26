"use client";

import { useCallback, useEffect, useState } from "react";

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
    <div className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
      <span
        className={
          "h-1.5 w-1.5 rounded-full " + (status?.ready ? "bg-emerald-500" : "bg-zinc-400")
        }
      />
      <span>
        {status?.ready ? `RAG: ${status.points_count} chunks indexed` : "RAG: empty index"}
      </span>
      <button
        type="button"
        onClick={generate}
        disabled={generating || !activeTenantId}
        className="rounded border border-black/10 px-2 py-0.5 text-[11px] disabled:opacity-40 dark:border-white/10"
      >
        {generating ? "Generating…" : "Generate"}
      </button>
      {message && <span>{message}</span>}
    </div>
  );
}
