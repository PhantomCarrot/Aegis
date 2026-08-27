"use client";

import { useEffect, useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";

type TenantConfig = {
  id: string;
  name: string;
  ollama: { url: string };
  exec: { mode: "local" | "ssh"; target: string; host?: string; port?: number; user?: string };
  kubeconfig_dir: string;
  tools_enabled: string[];
  domain_notes: string;
};

export function ConfigPanel({ activeTenantId }: { activeTenantId: string | null }) {
  const [config, setConfig] = useState<TenantConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeTenantId) return;
    apiFetch("/api/tenants/config")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setConfig)
      .catch((err) => setError(String(err)));
  }, [activeTenantId]);

  return (
    <Panel eyebrow="Active tenant configuration" category="settings" defaultOpen={false}>
      {error && <p className="text-xs text-aegis-danger">{error}</p>}
      {!error && !activeTenantId && <p className="text-xs text-aegis-faint">No active tenant</p>}
      {!error && activeTenantId && !config && <p className="text-xs text-aegis-faint">Loading…</p>}
      {config && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-aegis-faint">Tenant</dt>
          <dd className="font-mono text-aegis-text">
            {config.id} ({config.name})
          </dd>

          <dt className="text-aegis-faint">Execution</dt>
          <dd className="font-mono text-aegis-text">
            {config.exec.mode === "local" ? "local (backend machine)" : `remote — ${config.exec.target}`}
          </dd>

          <dt className="text-aegis-faint">Ollama</dt>
          <dd className="font-mono text-aegis-text">{config.ollama.url}</dd>

          <dt className="text-aegis-faint">Kubeconfig</dt>
          <dd className="font-mono text-aegis-text">{config.kubeconfig_dir}</dd>

          <dt className="text-aegis-faint">Enabled tools</dt>
          <dd className="font-mono text-aegis-text">{config.tools_enabled.join(", ") || "(none)"}</dd>

          {config.domain_notes && (
            <>
              <dt className="text-aegis-faint">Notes</dt>
              <dd className="whitespace-pre-wrap text-aegis-text">{config.domain_notes}</dd>
            </>
          )}
        </dl>
      )}
    </Panel>
  );
}
