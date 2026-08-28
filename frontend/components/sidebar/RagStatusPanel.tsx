"use client";

import { useCallback, useEffect, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";

type Status = { ready: boolean; points_count: number; generated_at: string | null };

const RELATIVE_TIME_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];
const relativeTimeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "generated 3m ago"-style freshness label — no new dependency, Intl covers it. */
function relativeTime(iso: string): string {
  const diffSeconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  for (const [unit, secondsInUnit] of RELATIVE_TIME_UNITS) {
    if (diffSeconds >= secondsInUnit) {
      return relativeTimeFormatter.format(-Math.round(diffSeconds / secondsInUnit), unit);
    }
  }
  return diffSeconds < 5 ? "just now" : relativeTimeFormatter.format(-diffSeconds, "second");
}

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
          // generate() indexes one document per source (kubectl always,
          // Terraform state too if the tenant has terraform_dir set) —
          // see docs/rag.md.
          const total = body.documents.reduce((sum: number, d: { chunks_indexed: number }) => sum + d.chunks_indexed, 0);
          const label = body.documents.length > 1 ? `${body.documents.length} documents` : "1 document";
          setMessage(`✓ ${total} chunks indexed (${label})`);
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
          {status?.ready
            ? `${status.points_count} chunks indexed` +
              (status.generated_at ? ` · generated ${relativeTime(status.generated_at)}` : "")
            : "empty index"}
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
