"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";
import { useTenant } from "@/hooks/useTenant";
import type { TenantFullConfig } from "@/lib/types";

import { TenantForm } from "./TenantForm";

type View = { mode: "list" } | { mode: "create" } | { mode: "edit"; tenantId: string };

export function TenantAdminPanel() {
  const tenant = useTenant();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>({ mode: "list" });
  const [editData, setEditData] = useState<TenantFullConfig | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  // Feedback from this panel's own actions (save/delete/set-default) — kept
  // separate from tenant.message, which is the shared context's own load error.
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const toggleOpen = () => setOpen((v) => !v);

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
    <div className="rounded-lg border border-black/10 text-xs dark:border-white/10">
      <button
        type="button"
        onClick={toggleOpen}
        className="flex w-full items-center justify-between px-3 py-2 text-zinc-600 dark:text-zinc-300"
      >
        <span>🗂️ Tenant administration</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-2 border-t border-black/10 px-3 py-2 dark:border-white/10">
          {tenant.status === "loading" && <p className="text-zinc-400">Loading…</p>}
          {tenant.status === "error" && <p className="text-red-500">{tenant.message}</p>}

          {tenant.status === "ready" && view.mode === "list" && (
            <>
              <div className="flex flex-col gap-1.5">
                {tenantList.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-black/10 px-2 py-1.5 dark:border-white/10"
                  >
                    <span className="font-mono">
                      {t.id} <span className="text-zinc-400">({t.name})</span>
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => setAsDefault(t.id)}
                        className="rounded border border-black/10 px-1.5 py-0.5 text-[11px] dark:border-white/10"
                        title="Set as default tenant"
                      >
                        Set default
                      </button>
                      <button
                        type="button"
                        onClick={() => startEdit(t.id)}
                        className="rounded border border-black/10 px-1.5 py-0.5 text-[11px] dark:border-white/10"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => requestDelete(t.id)}
                        className="rounded border border-black/10 px-1.5 py-0.5 text-[11px] text-red-500 dark:border-white/10"
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
                className="self-start rounded border border-black/10 px-2 py-1 dark:border-white/10"
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
              {!editData && <p className="text-zinc-400">Loading…</p>}
              {editData && (
                <TenantForm mode="edit" initial={editData} onSaved={onSaved} onCancel={backToList} />
              )}
            </>
          )}

          {actionMessage && <p>{actionMessage}</p>}
        </div>
      )}
    </div>
  );
}
