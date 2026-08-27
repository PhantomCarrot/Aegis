"use client";

import { useEffect, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";

type Provider = "ollama" | "lmstudio" | "airllm";

type ModelsResponse = {
  provider: Provider;
  models: string[];
  ollama_url?: string;
  lmstudio_url?: string;
  error?: string;
};

const PROVIDER_LABEL: Record<Provider, string> = {
  ollama: "Ollama model",
  lmstudio: "LM Studio model",
  airllm: "AirLLM model",
};

/**
 * Chat model used for this conversation — chosen from what's available on
 * the *active tenant's* LLM provider (Ollama, LM Studio, or AirLLM; local
 * or remote for the first two — see docs/llm-providers.md). Sent in the
 * body of /api/chat (see ChatPanel.tsx); if empty, the backend falls back
 * to its own default for that provider.
 *
 * AirLLM has no live model discovery — its model is a fixed part of the
 * tenant config, not something to pick at runtime (loading a different
 * checkpoint on demand isn't a "just pick from a dropdown" operation given
 * the cost) — the select is disabled with that one option, not hidden, so
 * it's still clear what's actually running.
 */
export function ModelSelector({
  activeTenantId,
  value,
  onChange,
}: {
  activeTenantId: string | null;
  value: string | null;
  onChange: (model: string) => void;
}) {
  const [models, setModels] = useState<string[] | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [endpointUrl, setEndpointUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeTenantId) return;

    apiFetch("/api/llm/models")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as ModelsResponse;
      })
      .then((body) => {
        setProvider(body.provider);
        setEndpointUrl(body.ollama_url ?? body.lmstudio_url ?? null);
        setError(body.error ?? null);
        setModels(body.models);
        // The active model belongs to a different tenant/provider, or none
        // has been chosen yet: fall back to the first one available.
        if (body.models.length > 0 && (!value || !body.models.includes(value))) {
          onChange(body.models[0]);
        }
      })
      .catch((err) => setError(String(err)));
    // value/onChange deliberately absent from deps: we only want to re-fetch
    // on a tenant change, not on every selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTenantId]);

  const isFixed = provider === "airllm";

  return (
    <Panel eyebrow={provider ? PROVIDER_LABEL[provider] : "Model"} category="settings" collapsible={false}>
      {endpointUrl && (
        <span className="truncate font-mono text-[10px] text-aegis-faint" title={endpointUrl}>
          {endpointUrl}
        </span>
      )}
      {error && <p className="text-xs text-aegis-danger">{error}</p>}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        disabled={isFixed || !models || models.length === 0}
        title={isFixed ? "Fixed by this tenant's llm.airllm.model config — see docs/llm-providers.md" : undefined}
        className="rounded-md border border-aegis-border bg-aegis-surface-2 px-2 py-1.5 text-sm text-aegis-text disabled:opacity-40"
      >
        {/* Distinct from "Loading…" — no active tenant means no fetch was
            ever attempted, so it must never look like one is in flight. */}
        {!activeTenantId && <option>No active tenant</option>}
        {activeTenantId && !models && <option>Loading…</option>}
        {activeTenantId && models?.length === 0 && <option>No model available</option>}
        {models?.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </Panel>
  );
}
