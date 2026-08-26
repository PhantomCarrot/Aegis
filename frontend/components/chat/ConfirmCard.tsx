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
      className={
        "rounded-md border p-3 text-sm " +
        (isDestructive
          ? "border-red-500/40 bg-red-500/10"
          : "border-amber-500/40 bg-amber-500/10")
      }
    >
      <div className={isDestructive ? "font-medium text-red-600 dark:text-red-400" : "font-medium text-amber-700 dark:text-amber-400"}>
        {isDestructive ? "⚠️ Destructive action" : "✏️ Confirmation required"} — {toolName}
      </div>
      {details && (
        <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-zinc-700 dark:text-zinc-300">
          {details.summary}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => onRespond(true)}
          className="rounded bg-black px-3 py-1.5 text-xs text-white dark:bg-white dark:text-black"
        >
          Confirm
        </button>
        <button
          type="button"
          onClick={() => onRespond(false)}
          className="rounded border border-black/20 px-3 py-1.5 text-xs text-zinc-700 dark:border-white/20 dark:text-zinc-300"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
