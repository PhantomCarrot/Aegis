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
    <details className="rounded-md border border-aegis-border border-l-2 border-l-aegis-warn bg-aegis-surface-2 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none font-mono text-aegis-dim">
        🔧 {part.toolName} — {STATE_LABEL[part.state] ?? part.state}
        {via && <span className="text-aegis-faint"> · executed via {via}</span>}
      </summary>
      <div className="mt-2 space-y-2">
        {"input" in part && part.input !== undefined && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-aegis-faint">input</div>
            <pre className="overflow-x-auto rounded bg-aegis-bg p-2 text-aegis-text">
              {JSON.stringify(part.input, null, 2)}
            </pre>
          </div>
        )}
        {part.state === "output-available" && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-aegis-faint">output</div>
            <pre className="overflow-x-auto rounded bg-aegis-bg p-2 text-aegis-text">
              {JSON.stringify(part.output, null, 2)}
            </pre>
          </div>
        )}
        {isError && <div className="text-aegis-danger">{part.errorText}</div>}
      </div>
    </details>
  );
}
