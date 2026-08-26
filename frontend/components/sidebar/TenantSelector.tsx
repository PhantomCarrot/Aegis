"use client";

import { useTenant } from "@/hooks/useTenant";

export function TenantSelector() {
  const tenant = useTenant();

  if (tenant.status === "loading") {
    return <p className="text-xs text-zinc-500 dark:text-zinc-400">Loading tenants…</p>;
  }

  if (tenant.status === "error") {
    return (
      <p className="max-w-xs text-center text-xs text-red-500" role="alert">
        {tenant.message}
      </p>
    );
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-zinc-500 dark:text-zinc-400">Tenant</span>
      <select
        value={tenant.activeTenantId}
        onChange={(e) => tenant.switchTenant(e.target.value)}
        className="rounded-md border border-black/10 bg-white px-3 py-1.5 text-sm text-black dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-50"
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
