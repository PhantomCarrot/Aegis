"use client";

import { useState } from "react";

import { Panel } from "@/components/ui/Panel";
import { apiFetch } from "@/lib/api";
import { useTenant } from "@/hooks/useTenant";
import type { TenantFullConfig } from "@/lib/types";

import { TenantForm } from "./TenantForm";

type View = { mode: "list" } | { mode: "create" } | { mode: "edit"; tenantId: string };

export function TenantAdminPanel() {
  const tenant = useTenant();
  const [view, setView] = useState<View>({ mode: "list" });
  const [editData, setEditData] = useState<TenantFullConfig | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  // Feedback from this panel's own actions (save/delete/set-default) — kept
  // separate from tenant.message, which is the shared context's own load error.
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const startEdit = (tenantId: string) => {
    setActionMessage(null);
    setEditData(null);
    setView({ mode: "edit", tenantId });
    apiFetch(`/api/tenants/${tenantId}`)
      .then((r) => r.json())
      .then(setEditData)
      .catch((err) => setActionMessage(`⚠ ${String(err)}`));
  };

  const backToList = () => {
    setView({ mode: "list" });
    setEditData(null);
    setPendingDelete(null);
  };

  const onSaved = () => {
    setActionMessage("✓ Tenant saved");
    tenant.reload();
    backToList();
  };

  const requestDelete = (tenantId: string) => {
    if (pendingDelete !== tenantId) {
      setPendingDelete(tenantId);
      return;
    }
    setActionMessage(null);
    apiFetch(`/api/tenants/${tenantId}`, { method: "DELETE" })
      .then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.detail ?? `HTTP ${r.status}`);
        }
        setActionMessage("✓ Tenant deleted");
        tenant.reload();
      })
      .catch((err) => setActionMessage(`⚠ ${String(err)}`))
      .finally(() => setPendingDelete(null));
  };

  const setAsDefault = (tenantId: string) => {
    setActionMessage(null);
    apiFetch("/api/tenants/default", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenantId }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.detail ?? `HTTP ${r.status}`);
        }
        setActionMessage(`✓ ${tenantId} is now the default`);
        tenant.reload();
      })
      .catch((err) => setActionMessage(`⚠ ${String(err)}`));
  };

  const tenantList = tenant.status === "ready" ? tenant.tenants : [];

  return (
    <Panel eyebrow="Tenant administration" category="tenants" defaultOpen={false}>
      {tenant.status === "loading" && <p className="text-xs text-aegis-faint">Loading…</p>}
      {tenant.status === "error" && <p className="text-xs text-aegis-danger">{tenant.message}</p>}

      {tenant.status === "ready" && view.mode === "list" && (
        <>
          <div className="flex flex-col gap-1.5">
            {tenantList.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between gap-2 rounded-md border border-aegis-border bg-aegis-surface-2 px-2 py-1.5 text-xs"
              >
                <span className="font-mono text-aegis-text">
                  {t.id} <span className="text-aegis-faint">({t.name})</span>
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setAsDefault(t.id)}
                    className="rounded border border-aegis-border px-1.5 py-0.5 text-[11px] text-aegis-dim hover:text-aegis-text"
                    title="Set as default tenant"
                  >
                    Set default
                  </button>
                  <button
                    type="button"
                    onClick={() => startEdit(t.id)}
                    className="rounded border border-aegis-border px-1.5 py-0.5 text-[11px] text-aegis-dim hover:text-aegis-text"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => requestDelete(t.id)}
                    className="rounded border border-aegis-border px-1.5 py-0.5 text-[11px] text-aegis-danger"
                  >
                    {pendingDelete === t.id ? "Confirm delete?" : "Delete"}
                  </button>
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setView({ mode: "create" })}
            className="self-start rounded-md border border-dashed border-aegis-faint px-2 py-1 text-xs font-semibold text-aegis-accent"
          >
            + New tenant
          </button>
        </>
      )}

      {view.mode === "create" && (
        <TenantForm mode="create" initial={null} onSaved={onSaved} onCancel={backToList} />
      )}

      {view.mode === "edit" && (
        <>
          {!editData && <p className="text-xs text-aegis-faint">Loading…</p>}
          {editData && <TenantForm mode="edit" initial={editData} onSaved={onSaved} onCancel={backToList} />}
        </>
      )}

      {actionMessage && <p className="text-xs text-aegis-text">{actionMessage}</p>}
    </Panel>
  );
}
