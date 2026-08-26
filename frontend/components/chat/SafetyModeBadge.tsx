"use client";

const MODES = [
  { value: "readonly", label: "ReadOnly", hint: "Read-only — nothing can be changed." },
  { value: "modify", label: "Modify", hint: "Changes require confirmation, deletions are refused." },
  { value: "root", label: "Root", hint: "Everything is allowed, but changes AND deletions require confirmation." },
] as const;

export type SafetyMode = (typeof MODES)[number]["value"];

export function SafetyModeBadge({
  value,
  onChange,
}: {
  value: SafetyMode;
  onChange: (mode: SafetyMode) => void;
}) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-black/10 bg-white p-1 text-xs dark:border-white/10 dark:bg-zinc-900">
      {MODES.map((mode) => (
        <button
          key={mode.value}
          type="button"
          title={mode.hint}
          onClick={() => onChange(mode.value)}
          className={
            "rounded-full px-3 py-1 transition-colors " +
            (value === mode.value
              ? "bg-black text-white dark:bg-white dark:text-black"
              : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100")
          }
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
