"use client";

import { useTenant } from "@/hooks/useTenant";

export function TenantSelector() {
  const tenant = useTenant();

  if (tenant.status === "loading") {
    return <p className="text-xs text-aegis-dim">Loading tenants…</p>;
  }

  if (tenant.status === "error") {
    return (
      <p className="max-w-xs text-center text-xs text-aegis-danger" role="alert">
        {tenant.message}
      </p>
    );
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-aegis-dim">Tenant</span>
      <select
        value={tenant.activeTenantId}
        onChange={(e) => tenant.switchTenant(e.target.value)}
        className="rounded-md border border-aegis-border bg-aegis-surface px-3 py-1.5 text-sm text-aegis-text"
      >
        {tenant.tenants.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  );
}
