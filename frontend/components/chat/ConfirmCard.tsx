"use client";

type ApprovalDetails = { summary: string; category: "mutant" | "destructive" | string };

export function ConfirmCard({
  toolName,
  details,
  onRespond,
}: {
  toolName: string;
  details?: ApprovalDetails;
  onRespond: (approved: boolean) => void;
}) {
  const isDestructive = details?.category === "destructive";
  return (
    <div
      className="rounded-md border p-3 text-sm"
      style={{
        borderColor: isDestructive ? "var(--aegis-danger)" : "var(--aegis-warn)",
        backgroundColor: isDestructive ? "var(--aegis-danger-bg)" : "var(--aegis-warn-bg)",
      }}
    >
      <div className="font-medium" style={{ color: isDestructive ? "var(--aegis-danger)" : "var(--aegis-warn)" }}>
        {isDestructive ? "⚠️ Destructive action" : "✏️ Confirmation required"} — {toolName}
      </div>
      {details && <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-aegis-text">{details.summary}</p>}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => onRespond(true)}
          className="rounded bg-aegis-accent px-3 py-1.5 text-xs font-semibold text-aegis-accent-ink"
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => onRespond(false)}
          className="rounded border border-aegis-border px-3 py-1.5 text-xs text-aegis-dim"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
