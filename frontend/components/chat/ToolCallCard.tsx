"use client";

import type { DynamicToolUIPart } from "ai";

const STATE_LABEL: Record<string, string> = {
  "input-streaming": "preparing…",
  "input-available": "in progress…",
  "approval-requested": "confirmation required",
  "approval-responded": "confirmed",
  "output-available": "done",
  "output-error": "error",
  "output-denied": "denied",
};

function executedVia(part: DynamicToolUIPart): string | null {
  if (part.state !== "output-available") return null;
  const output = part.output as { executed_via?: string } | undefined;
  return output?.executed_via ?? null;
}

export function ToolCallCard({ part }: { part: DynamicToolUIPart }) {
  const isError = part.state === "output-error";
  const via = executedVia(part);
  return (
    <details className="rounded-md border border-black/10 bg-white/50 px-3 py-2 text-xs dark:border-white/10 dark:bg-white/5">
      <summary className="cursor-pointer select-none font-mono text-zinc-600 dark:text-zinc-400">
        🔧 {part.toolName} — {STATE_LABEL[part.state] ?? part.state}
        {via && <span className="text-zinc-400"> · executed via {via}</span>}
      </summary>
      <div className="mt-2 space-y-2">
        {"input" in part && part.input !== undefined && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-zinc-400">input</div>
            <pre className="overflow-x-auto rounded bg-black/5 p-2 dark:bg-white/5">
              {JSON.stringify(part.input, null, 2)}
            </pre>
          </div>
        )}
        {part.state === "output-available" && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-zinc-400">output</div>
            <pre className="overflow-x-auto rounded bg-black/5 p-2 dark:bg-white/5">
              {JSON.stringify(part.output, null, 2)}
            </pre>
          </div>
        )}
        {isError && (
          <div className="text-red-500">{part.errorText}</div>
        )}
      </div>
    </details>
  );
}
