"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import type { ExecConfig, LLMConfig, TenantFullConfig } from "@/lib/types";

// Same pattern the backend enforces server-side (see _TENANT_ID_PATTERN in
// backend/app/routers/tenants.py) — checked here too so a bad id shows an
// inline error instead of a round trip to learn the same thing.
const ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

type FormState = {
  id: string;
  name: string;
  ollamaUrl: string;
  llmProvider: "ollama" | "lmstudio" | "airllm";
  lmstudioUrl: string;
  airllmModel: string;
  airllmDevice: string;
  airllmCompression: "" | "4bit" | "8bit";
  airllmMaxSeqLen: number;
  airllmMaxNewTokens: number;
  execMode: "local" | "ssh";
  sshHost: string;
  sshUser: string;
  sshPort: number;
  sshKeyPath: string;
  sshCertificatePath: string;
  sshKnownHostsPath: string;
  kubeconfigDir: string;
  toolGroups: string[];
  domainNotes: string;
};

const EMPTY_FORM: FormState = {
  id: "",
  name: "",
  ollamaUrl: "http://localhost:11434",
  llmProvider: "ollama",
  lmstudioUrl: "http://localhost:1234",
  airllmModel: "",
  airllmDevice: "cpu",
  airllmCompression: "",
  airllmMaxSeqLen: 2048,
  airllmMaxNewTokens: 512,
  execMode: "local",
  sshHost: "",
  sshUser: "",
  sshPort: 22,
  sshKeyPath: "",
  sshCertificatePath: "",
  sshKnownHostsPath: "",
  kubeconfigDir: "",
  toolGroups: [],
  domainNotes: "",
};

function fromTenant(t: TenantFullConfig): FormState {
  return {
    id: t.id,
    name: t.name,
    ollamaUrl: t.ollama.url,
    llmProvider: t.llm.provider,
    lmstudioUrl: t.llm.lmstudio.url,
    airllmModel: t.llm.airllm?.model ?? "",
    airllmDevice: t.llm.airllm?.device ?? "cpu",
    airllmCompression: t.llm.airllm?.compression ?? "",
    airllmMaxSeqLen: t.llm.airllm?.max_seq_len ?? 2048,
    airllmMaxNewTokens: t.llm.airllm?.max_new_tokens ?? 512,
    execMode: t.exec.mode,
    sshHost: t.exec.ssh?.host ?? "",
    sshUser: t.exec.ssh?.user ?? "",
    sshPort: t.exec.ssh?.port ?? 22,
    sshKeyPath: t.exec.ssh?.key_path ?? "",
    sshCertificatePath: t.exec.ssh?.certificate_path ?? "",
    sshKnownHostsPath: t.exec.ssh?.known_hosts_path ?? "",
    kubeconfigDir: t.kubeconfig_dir,
    toolGroups: t.tools_enabled,
    domainNotes: t.domain_notes,
  };
}

// Always sends every field explicitly (no attempt at a minimal diff against
// global.yaml's defaults) — the simplest correct behavior without a form
// library's notion of "inherited vs overridden". See docs/multi-tenant.md.
function toRequestBody(f: FormState): { name: string; ollama: { url: string }; llm: LLMConfig; exec: ExecConfig; kubeconfig_dir: string; tools_enabled: string[]; domain_notes: string } {
  const llm: LLMConfig = {
    provider: f.llmProvider,
    lmstudio: { url: f.lmstudioUrl },
    airllm:
      f.llmProvider === "airllm"
        ? {
            model: f.airllmModel,
            device: f.airllmDevice,
            compression: f.airllmCompression === "" ? null : f.airllmCompression,
            max_seq_len: f.airllmMaxSeqLen,
            max_new_tokens: f.airllmMaxNewTokens,
          }
        : null,
  };
  const exec: ExecConfig = {
    mode: f.execMode,
    ssh:
      f.execMode === "ssh"
        ? {
            host: f.sshHost,
            user: f.sshUser,
            port: f.sshPort,
            key_path: f.sshKeyPath,
            certificate_path: f.sshCertificatePath || null,
            known_hosts_path: f.sshKnownHostsPath || null,
          }
        : null,
  };
  return {
    name: f.name,
    ollama: { url: f.ollamaUrl },
    llm,
    exec,
    kubeconfig_dir: f.kubeconfigDir,
    tools_enabled: f.toolGroups,
    domain_notes: f.domainNotes,
  };
}

export function TenantForm({
  mode,
  initial,
  onSaved,
  onCancel,
}: {
  mode: "create" | "edit";
  /** Full config to prefill, for edit mode — null in create mode. */
  initial: TenantFullConfig | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial ? fromTenant(initial) : EMPTY_FORM);
  const [groups, setGroups] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    // The tool-group checklist (kubectl/argocd/cloud_cli/run_command) comes
    // from the backend's registry rather than being hardcoded here — see
    // ui_tool_groups() in app/agent/tools/registry.py.
    apiFetch("/api/tools")
      .then((r) => r.json())
      .then((body) => setGroups(body.groups ?? []))
      .catch(() => setGroups([]));
  }, []);

  const idIsValid = mode === "edit" || ID_PATTERN.test(form.id);

  const toggleGroup = (group: string) => {
    setForm((f) => ({
      ...f,
      toolGroups: f.toolGroups.includes(group)
        ? f.toolGroups.filter((g) => g !== group)
        : [...f.toolGroups, group],
    }));
  };

  const submit = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const body = toRequestBody(form);
      const res =
        mode === "create"
          ? await apiFetch("/api/tenants", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: form.id, ...body }),
            })
          : await apiFetch(`/api/tenants/${initial!.id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setMessage(`⚠ ${err.detail ?? `HTTP ${res.status}`}`);
        return;
      }
      onSaved();
    } catch (err) {
      setMessage(`⚠ ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-md border border-aegis-border bg-aegis-surface-2 p-3 text-xs">
      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Tenant id</label>
        <input
          type="text"
          value={form.id}
          disabled={mode === "edit"}
          onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
          placeholder="acme-corp"
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text disabled:opacity-50"
        />
        {mode === "create" && form.id && !idIsValid && (
          <span className="text-aegis-danger">
            lowercase letters, digits, hyphens only — can&apos;t start/end with a hyphen
          </span>
        )}
        {mode === "edit" && (
          <span className="text-aegis-faint">Can&apos;t be renamed — delete and recreate instead.</span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Name</label>
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 text-aegis-text"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Ollama URL (chat default + always used for RAG embeddings)</label>
        <input
          type="text"
          value={form.ollamaUrl}
          onChange={(e) => setForm((f) => ({ ...f, ollamaUrl: e.target.value }))}
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">LLM provider</label>
        <select
          value={form.llmProvider}
          onChange={(e) =>
            setForm((f) => ({ ...f, llmProvider: e.target.value as FormState["llmProvider"] }))
          }
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 text-aegis-text"
        >
          <option value="ollama">Ollama</option>
          <option value="lmstudio">LM Studio</option>
          <option value="airllm">AirLLM</option>
        </select>
      </div>

      {form.llmProvider === "lmstudio" && (
        <div className="flex flex-col gap-1 border-l-2 border-aegis-border pl-3">
          <label className="text-aegis-faint">LM Studio URL</label>
          <input
            type="text"
            value={form.lmstudioUrl}
            onChange={(e) => setForm((f) => ({ ...f, lmstudioUrl: e.target.value }))}
            className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
          />
        </div>
      )}

      {form.llmProvider === "airllm" && (
        <div className="flex flex-col gap-2 border-l-2 border-aegis-border pl-3">
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Model (HF repo id or local path)</label>
            <input
              type="text"
              value={form.airllmModel}
              onChange={(e) => setForm((f) => ({ ...f, airllmModel: e.target.value }))}
              placeholder="meta-llama/Llama-3.2-3B-Instruct"
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Device</label>
            <input
              type="text"
              value={form.airllmDevice}
              onChange={(e) => setForm((f) => ({ ...f, airllmDevice: e.target.value }))}
              placeholder="cpu"
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Compression</label>
            <select
              value={form.airllmCompression}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  airllmCompression: e.target.value as FormState["airllmCompression"],
                }))
              }
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 text-aegis-text"
            >
              <option value="">none</option>
              <option value="4bit">4bit</option>
              <option value="8bit">8bit</option>
            </select>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Execution</label>
        <select
          value={form.execMode}
          onChange={(e) => setForm((f) => ({ ...f, execMode: e.target.value as FormState["execMode"] }))}
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 text-aegis-text"
        >
          <option value="local">Local</option>
          <option value="ssh">SSH</option>
        </select>
      </div>

      {form.execMode === "ssh" && (
        <div className="flex flex-col gap-2 border-l-2 border-aegis-border pl-3">
          <div className="flex gap-2">
            <div className="flex flex-1 flex-col gap-1">
              <label className="text-aegis-faint">Host</label>
              <input
                type="text"
                value={form.sshHost}
                onChange={(e) => setForm((f) => ({ ...f, sshHost: e.target.value }))}
                className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
              />
            </div>
            <div className="w-16 flex-none flex-col gap-1">
              <label className="text-aegis-faint">Port</label>
              <input
                type="number"
                value={form.sshPort}
                onChange={(e) => setForm((f) => ({ ...f, sshPort: Number(e.target.value) || 22 }))}
                className="w-full rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">User</label>
            <input
              type="text"
              value={form.sshUser}
              onChange={(e) => setForm((f) => ({ ...f, sshUser: e.target.value }))}
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Key path</label>
            <input
              type="text"
              value={form.sshKeyPath}
              onChange={(e) => setForm((f) => ({ ...f, sshKeyPath: e.target.value }))}
              placeholder="~/.ssh/aegis_acme-corp"
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Certificate path (optional)</label>
            <input
              type="text"
              value={form.sshCertificatePath}
              onChange={(e) => setForm((f) => ({ ...f, sshCertificatePath: e.target.value }))}
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-aegis-faint">Known hosts path (optional, recommended)</label>
            <input
              type="text"
              value={form.sshKnownHostsPath}
              onChange={(e) => setForm((f) => ({ ...f, sshKnownHostsPath: e.target.value }))}
              className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
            />
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Kubeconfig dir (blank → ~/.kube/aegis/{"{id}"})</label>
        <input
          type="text"
          value={form.kubeconfigDir}
          onChange={(e) => setForm((f) => ({ ...f, kubeconfigDir: e.target.value }))}
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 font-mono text-aegis-text"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Tools</label>
        <div className="flex flex-wrap gap-3">
          {groups.map((group) => (
            <label key={group} className="flex items-center gap-1.5 text-aegis-text">
              <input
                type="checkbox"
                checked={form.toolGroups.includes(group)}
                onChange={() => toggleGroup(group)}
                className="accent-[color:var(--aegis-accent)]"
              />
              <span className="font-mono">{group}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-aegis-faint">Domain notes</label>
        <textarea
          value={form.domainNotes}
          onChange={(e) => setForm((f) => ({ ...f, domainNotes: e.target.value }))}
          rows={3}
          className="rounded border border-aegis-border bg-aegis-surface px-2 py-1 text-aegis-text"
        />
      </div>

      {message && <p className="text-aegis-danger">{message}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={saving || !form.name || !form.id || !idIsValid}
          className="rounded-md bg-aegis-accent px-3 py-1 font-semibold text-aegis-accent-ink disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded-md border border-aegis-border px-3 py-1 text-aegis-dim disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
