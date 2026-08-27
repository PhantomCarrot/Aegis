"use client";

import { Segmented } from "@/components/ui/Segmented";

const MODES = [
  { value: "readonly", label: "ReadOnly", title: "Read-only — nothing can be changed." },
  { value: "modify", label: "Modify", title: "Changes require confirmation, deletions are refused." },
  { value: "root", label: "Root", title: "Everything is allowed, but changes AND deletions require confirmation." },
] as const;

export type SafetyMode = (typeof MODES)[number]["value"];

export function SafetyModeBadge({
  value,
  onChange,
}: {
  value: SafetyMode;
  onChange: (mode: SafetyMode) => void;
}) {
  return <Segmented ariaLabel="Safety mode" options={[...MODES]} value={value} onChange={onChange} />;
}
