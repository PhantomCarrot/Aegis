"use client";

import { Segmented } from "@/components/ui/Segmented";

const MODES = [
  { value: "readonly", label: "ReadOnly", title: "Read-only — nothing can be changed." },
  { value: "modify", label: "Modify", title: "Changes require confirmation, deletions are refused." },
  { value: "root", label: "Root", title: "Everything is allowed, but changes AND deletions require confirmation." },
] as const;

export type SafetyMode = (typeof MODES)[number]["value"];

// Reused by StatusStrip, which shows the current mode without rendering the
// full segmented control.
export const SAFETY_MODE_LABEL: Record<SafetyMode, string> = Object.fromEntries(
  MODES.map((m) => [m.value, m.label]),
) as Record<SafetyMode, string>;

export function SafetyModeBadge({
  value,
  onChange,
}: {
  value: SafetyMode;
  onChange: (mode: SafetyMode) => void;
}) {
  return <Segmented ariaLabel="Safety mode" options={[...MODES]} value={value} onChange={onChange} />;
}
