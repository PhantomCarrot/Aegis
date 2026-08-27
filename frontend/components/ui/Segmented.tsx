"use client";

/** Shared pill-group control — safety mode, chat mode, and any future
 * small exclusive choice all use this instead of each hand-rolling one. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { value: T; label: string; title?: string }[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="flex items-center gap-1 rounded-full border border-aegis-border bg-aegis-surface-2 p-1 text-xs"
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          title={opt.title}
          aria-pressed={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={
            "flex-1 rounded-full px-3 py-1 font-semibold transition-colors " +
            (value === opt.value
              ? "bg-aegis-accent text-aegis-accent-ink"
              : "text-aegis-dim hover:text-aegis-text")
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
