"use client";

import { useEffect, useState } from "react";

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
  const [open, setOpen] = useState(false);
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
    <div className="w-full max-w-2xl rounded-lg border border-black/10 bg-white/50 text-xs dark:border-white/10 dark:bg-white/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-zinc-600 dark:text-zinc-300"
      >
        <span>⚙️ Active tenant configuration</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="border-t border-black/10 px-3 py-2 dark:border-white/10">
          {error && <p className="text-red-500">{error}</p>}
          {!error && !activeTenantId && <p className="text-zinc-400">No active tenant</p>}
          {!error && activeTenantId && !config && <p className="text-zinc-400">Loading…</p>}
          {config && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-zinc-400">Tenant</dt>
              <dd className="font-mono">{config.id} ({config.name})</dd>

              <dt className="text-zinc-400">Execution</dt>
              <dd className="font-mono">
                {config.exec.mode === "local"
                  ? "local (backend machine)"
                  : `remote — ${config.exec.target}`}
              </dd>

              <dt className="text-zinc-400">Ollama</dt>
              <dd className="font-mono">{config.ollama.url}</dd>

              <dt className="text-zinc-400">Kubeconfig</dt>
              <dd className="font-mono">{config.kubeconfig_dir}</dd>

              <dt className="text-zinc-400">Enabled tools</dt>
              <dd className="font-mono">{config.tools_enabled.join(", ") || "(none)"}</dd>

              {config.domain_notes && (
                <>
                  <dt className="text-zinc-400">Notes</dt>
                  <dd className="whitespace-pre-wrap">{config.domain_notes}</dd>
                </>
              )}
            </dl>
          )}
        </div>
      )}
    </div>
  );
}
