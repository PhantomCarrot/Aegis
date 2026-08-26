"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";

type ToolInfo = {
  name: string;
  enabled: boolean; // allowed by tenant config (upper bound, see docs/tools.md)
  guarded: boolean; // subject to guardrails (confirmation may be required)
  schema: { type: string; function: { name: string; description: string; parameters: unknown } };
};

/**
 * Runtime tool toggle for the current conversation — can only NARROW what
 * the tenant config allows (tool.enabled), never widen it. See docs/tools.md
 * for the exact security boundary (re-checked server-side; this is a UI
 * convenience only).
 *
 * `enabledTools` (prop): null = no restriction (everything `enabled` by
 * config is active); otherwise the explicit list of checked tools.
 */
export function ToolsPanel({
  activeTenantId,
  enabledTools,
  onChangeEnabledTools,
}: {
  activeTenantId: string | null;
  enabledTools: string[] | null;
  onChangeEnabledTools: (names: string[] | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!activeTenantId) return;
    setLoading(true);
    apiFetch("/api/tools")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((body) => {
        setTools(body.tools);
        setError(null);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    if (next && tools === null) load();
  };

  const allowedByConfig = (tools ?? []).filter((t) => t.enabled).map((t) => t.name);

  const isChecked = (name: string): boolean =>
    allowedByConfig.includes(name) && (enabledTools === null || enabledTools.includes(name));

  const toggleTool = (name: string) => {
    const checked = new Set(enabledTools ?? allowedByConfig);
    if (checked.has(name)) {
      checked.delete(name);
    } else {
      checked.add(name);
    }
    const asArray = [...checked];
    // If the result matches exactly what the tenant config already allows,
    // fall back to "no restriction" (null) instead of keeping a redundant
    // override sent on every request.
    const matchesConfigDefault =
      asArray.length === allowedByConfig.length && asArray.every((n) => allowedByConfig.includes(n));
    onChangeEnabledTools(matchesConfigDefault ? null : asArray);
  };

  return (
    <div className="rounded-lg border border-black/10 text-xs dark:border-white/10">
      <button
        type="button"
        onClick={toggleOpen}
        className="flex w-full items-center justify-between px-3 py-2 text-zinc-600 dark:text-zinc-300"
      >
        <span>🧰 Tools</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="border-t border-black/10 px-3 py-2 dark:border-white/10">
          {!activeTenantId && <p className="text-zinc-400">No active tenant</p>}
          {loading && <p className="text-zinc-400">Loading…</p>}
          {error && <p className="text-red-500">{error}</p>}
          <div className="flex flex-col gap-1.5">
            {tools?.map((tool) => (
              <div
                key={tool.name}
                className="rounded-md border border-black/10 px-2 py-1.5 dark:border-white/10"
              >
                <div className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={isChecked(tool.name)}
                      disabled={!tool.enabled}
                      onChange={() => toggleTool(tool.name)}
                    />
                    <span className="font-mono">{tool.name}</span>
                    {tool.guarded && (
                      <span
                        title="Subject to guardrails — confirmation may be required"
                        className="text-amber-500"
                      >
                        ⚠
                      </span>
                    )}
                  </label>
                  {!tool.enabled && (
                    <span className="text-[10px] text-zinc-400">not allowed (tenant config)</span>
                  )}
                </div>
                {tool.schema.function.description && (
                  <p className="mt-1 text-zinc-500 dark:text-zinc-400">
                    {tool.schema.function.description}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
