/**
 * Minimal REST client: prefixes calls with the BFF proxy and injects the
 * active tenant (X-Tenant-Id) from localStorage on every request — see
 * docs/multi-tenant.md for why (no global server-side state, the active
 * tenant is carried by the client).
 */
const TENANT_STORAGE_KEY = "aegis:activeTenantId";

export function getStoredTenantId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_STORAGE_KEY);
}

export function setStoredTenantId(tenantId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TENANT_STORAGE_KEY, tenantId);
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const tenantId = getStoredTenantId();
  const headers = new Headers(init.headers);
  if (tenantId) headers.set("X-Tenant-Id", tenantId);
  return fetch(`/api/backend${path}`, { ...init, headers });
}
