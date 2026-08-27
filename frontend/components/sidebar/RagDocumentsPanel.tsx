"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";

type Chunk = { chunk_index: number; heading_path: string; text: string };
type Doc = { source_path: string; chunk_count: number; chunks: Chunk[] };

export function RagDocumentsPanel({ activeTenantId }: { activeTenantId: string | null }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!activeTenantId || docs !== null) return;
    setLoading(true);
    setError(null);
    apiFetch("/api/rag/documents")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((body) => setDocs(body.documents))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <Panel eyebrow="Indexed content (RAG)" category="rag" defaultOpen={false} onOpen={load}>
      <div className="flex max-h-80 flex-col gap-2 overflow-y-auto text-xs">
        {!activeTenantId && <p className="text-aegis-faint">No active tenant</p>}
        {loading && <p className="text-aegis-faint">Loading…</p>}
        {error && <p className="text-aegis-danger">{error}</p>}
        {docs && docs.length === 0 && (
          <p className="text-aegis-faint">Nothing indexed for this tenant yet — click « Generate » above.</p>
        )}
        {docs?.map((doc) => (
          <details key={doc.source_path}>
            <summary className="cursor-pointer select-none font-mono text-aegis-dim">
              {doc.source_path} ({doc.chunk_count} chunks)
            </summary>
            <div className="mt-1 flex flex-col gap-2 pl-3">
              {doc.chunks.map((c) => (
                <div key={c.chunk_index} className="border-l-2 border-aegis-border pl-2">
                  {c.heading_path && (
                    <div className="text-[10px] uppercase tracking-wide text-aegis-faint">{c.heading_path}</div>
                  )}
                  <pre className="whitespace-pre-wrap text-aegis-dim">{c.text}</pre>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </Panel>
  );
}
