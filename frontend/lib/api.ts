/**
 * Minimal REST client: prefixes calls with the BFF proxy and injects the
 * active tenant (X-Tenant-Id) from localStorage on every request — see
 * docs/multi-tenant.md for why (no global server-side state, the active
 * tenant is carried by the client).
 */
const TENANT_STORAGE_KEY = "aegis:activeTenantId";
const MODEL_STORAGE_PREFIX = "aegis:model:";

export function getStoredTenantId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_STORAGE_KEY);
}

export function setStoredTenantId(tenantId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TENANT_STORAGE_KEY, tenantId);
}

// One remembered model per tenant, not a single global value — each
// tenant can be on a different provider/endpoint with a different set of
// models available (see ModelSelector.tsx), so "last picked" only makes
// sense scoped to the tenant it was picked for.
export function getStoredModel(tenantId: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(MODEL_STORAGE_PREFIX + tenantId);
}

export function setStoredModel(tenantId: string, model: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(MODEL_STORAGE_PREFIX + tenantId, model);
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const tenantId = getStoredTenantId();
  const headers = new Headers(init.headers);
  if (tenantId) headers.set("X-Tenant-Id", tenantId);
  return fetch(`/api/backend${path}`, { ...init, headers });
}
