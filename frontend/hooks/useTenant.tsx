"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { apiFetch, getStoredTenantId, setStoredTenantId } from "@/lib/api";
import type { Tenant, TenantsResponse } from "@/lib/types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tenants: Tenant[]; activeTenantId: string };

type FetchResult =
  | { ok: false; message: string }
  | { ok: true; tenants: Tenant[]; defaultTenant: string | null };

/** Pure function (never touches React state) — see applyFetchResult. */
async function fetchTenantsList(): Promise<FetchResult> {
  try {
    const res = await apiFetch("/api/tenants");
    // `detail` covers FastAPI's own error shape (auth failures, 5xx) — the
    // fetch can fail before ever reaching the handler that produces `error`,
    // and without this a backend misconfiguration (e.g. AEGIS_BACKEND_TOKENS
    // unset) was misreported as "no tenant configured", which it isn't.
    const body: TenantsResponse & { detail?: string } = await res.json();

    if (!res.ok || body.error || body.detail || body.tenants.length === 0) {
      return {
        ok: false,
        message: body.error ?? body.detail ?? "No tenant configured (config/tenants.yaml missing or empty).",
      };
    }
    return { ok: true, tenants: body.tenants, defaultTenant: body.default_tenant };
  } catch (err) {
    return { ok: false, message: String(err) };
  }
}

/**
 * Applies a fetch result to the current state via a functional update: if
 * the user already switched tenant while the request was in flight, we keep
 * their choice instead of overwriting it with the value read from
 * localStorage when the fetch started.
 */
function applyFetchResult(result: FetchResult): (prev: State) => State {
  return (prev) => {
    if (!result.ok) return { status: "error", message: result.message };

    const currentSelection = prev.status === "ready" ? prev.activeTenantId : null;
    const preferred = currentSelection ?? getStoredTenantId();
    const activeTenantId =
      preferred && result.tenants.some((t) => t.id === preferred)
        ? preferred
        : (result.defaultTenant ?? result.tenants[0]?.id ?? null);

    if (!activeTenantId) {
      return { status: "error", message: "No tenant available." };
    }
    setStoredTenantId(activeTenantId);
    return { status: "ready", tenants: result.tenants, activeTenantId };
  };
}

type TenantContextValue = State & {
  switchTenant: (tenantId: string) => void;
  reload: () => void;
};

// No default value: calling useTenant() outside <TenantProvider> is a
// programming error — we want it to blow up rather than silently produce
// inconsistent behavior.
const TenantContext = createContext<TenantContextValue | null>(null);

/**
 * Single source of truth for the active tenant — one <TenantProvider> at
 * the app root (see app/layout.tsx). Without it, each component calling its
 * own useTenant() would have independent state, and a switch in one
 * wouldn't propagate to the others.
 */
export function TenantProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchTenantsList().then((result) => {
      if (!cancelled) setState(applyFetchResult(result));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const reload = useCallback(() => {
    fetchTenantsList().then((result) => setState(applyFetchResult(result)));
  }, []);

  const switchTenant = useCallback((tenantId: string) => {
    setStoredTenantId(tenantId);
    setState((prev) => (prev.status === "ready" ? { ...prev, activeTenantId: tenantId } : prev));
  }, []);

  const value: TenantContextValue = { ...state, switchTenant, reload };
  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error("useTenant() must be used inside a <TenantProvider>.");
  }
  return ctx;
}
