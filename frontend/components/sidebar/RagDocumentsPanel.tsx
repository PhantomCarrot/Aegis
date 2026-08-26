"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";

type Chunk = { chunk_index: number; heading_path: string; text: string };
type Doc = { source_path: string; chunk_count: number; chunks: Chunk[] };

export function RagDocumentsPanel({ activeTenantId }: { activeTenantId: string | null }) {
  const [open, setOpen] = useState(false);
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!activeTenantId) return;
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

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && docs === null) load();
  };

  return (
    <div className="w-full max-w-2xl rounded-lg border border-black/10 bg-white/50 text-xs dark:border-white/10 dark:bg-white/5">
      <button
        type="button"
        onClick={toggle}
        className="flex w-full items-center justify-between px-3 py-2 text-zinc-600 dark:text-zinc-300"
      >
        <span>📚 Indexed content (RAG)</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto border-t border-black/10 px-3 py-2 dark:border-white/10">
          {!activeTenantId && <p className="text-zinc-400">No active tenant</p>}
          {loading && <p className="text-zinc-400">Loading…</p>}
          {error && <p className="text-red-500">{error}</p>}
          {docs && docs.length === 0 && (
            <p className="text-zinc-400">Nothing indexed for this tenant yet — click « Generate » above.</p>
          )}
          {docs?.map((doc) => (
            <details key={doc.source_path} className="mb-2">
              <summary className="cursor-pointer select-none font-mono text-zinc-600 dark:text-zinc-300">
                {doc.source_path} ({doc.chunk_count} chunks)
              </summary>
              <div className="mt-1 space-y-2 pl-3">
                {doc.chunks.map((c) => (
                  <div key={c.chunk_index} className="border-l-2 border-black/10 pl-2 dark:border-white/10">
                    {c.heading_path && (
                      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{c.heading_path}</div>
                    )}
                    <pre className="whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">{c.text}</pre>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
