"use client";

type RagSource = {
  index: number;
  source_path: string;
  heading_path: string;
  score: number;
};

export function RagSourcesFooter({ sources }: { sources: RagSource[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="rounded-md border border-aegis-border bg-aegis-surface-2 p-2 text-xs">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-aegis-faint">Sources</div>
      <ul className="space-y-0.5">
        {sources.map((s) => (
          <li key={s.index} className="text-aegis-dim">
            [{s.index}] {s.source_path}
            {s.heading_path ? ` — ${s.heading_path}` : ""}
            <span className="text-aegis-faint"> ({(s.score * 100).toFixed(0)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
