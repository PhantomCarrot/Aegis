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
    <div className="rounded-md border border-black/10 bg-black/5 p-2 text-xs dark:border-white/10 dark:bg-white/5">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-400">Sources</div>
      <ul className="space-y-0.5">
        {sources.map((s) => (
          <li key={s.index} className="text-zinc-600 dark:text-zinc-400">
            [{s.index}] {s.source_path}
            {s.heading_path ? ` — ${s.heading_path}` : ""}
            <span className="text-zinc-400 dark:text-zinc-600"> ({(s.score * 100).toFixed(0)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
