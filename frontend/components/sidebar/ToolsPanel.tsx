"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/Panel";
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
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!activeTenantId || tools !== null) return;
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
    <Panel eyebrow="Tools" category="settings" defaultOpen={false} onOpen={load}>
      {!activeTenantId && <p className="text-xs text-aegis-faint">No active tenant</p>}
      {loading && <p className="text-xs text-aegis-faint">Loading…</p>}
      {error && <p className="text-xs text-aegis-danger">{error}</p>}
      <div className="flex flex-col gap-1.5">
        {tools?.map((tool) => (
          <div key={tool.name} className="rounded-md border border-aegis-border bg-aegis-surface-2 px-2 py-1.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={isChecked(tool.name)}
                  disabled={!tool.enabled}
                  onChange={() => toggleTool(tool.name)}
                  className="accent-[color:var(--aegis-accent)]"
                />
                <span className="font-mono text-aegis-text">{tool.name}</span>
                {tool.guarded && (
                  <span title="Subject to guardrails — confirmation may be required" className="text-aegis-warn">
                    ⚠
                  </span>
                )}
              </label>
              {!tool.enabled && <span className="text-[10px] text-aegis-faint">not allowed (tenant config)</span>}
            </div>
            {tool.schema.function.description && (
              <p className="mt-1 text-aegis-dim">{tool.schema.function.description}</p>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}
