"use client";

import { useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { SafetyModeBadge, type SafetyMode } from "@/components/chat/SafetyModeBadge";
import { CollapsibleSidebar } from "@/components/layout/CollapsibleSidebar";
import { ConfigPanel } from "@/components/sidebar/ConfigPanel";
import { ModelSelector } from "@/components/sidebar/ModelSelector";
import { RagDocumentsPanel } from "@/components/sidebar/RagDocumentsPanel";
import { RagStatusPanel } from "@/components/sidebar/RagStatusPanel";
import { TenantAdminPanel } from "@/components/sidebar/TenantAdminPanel";
import { TenantSelector } from "@/components/sidebar/TenantSelector";
import { ToolsPanel } from "@/components/sidebar/ToolsPanel";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useTenant } from "@/hooks/useTenant";
import { apiFetch } from "@/lib/api";

type PingState =
  | { status: "loading" }
  | { status: "ok"; tenant: { id: string; name: string } }
  | { status: "error"; message: string };

type ChatMode = "ops" | "rag";

export default function Home() {
  const tenant = useTenant();
  const activeTenantId = tenant.status === "ready" ? tenant.activeTenantId : null;
  const [ping, setPing] = useState<PingState>({ status: "loading" });

  // Settings driven from the sidebars, consumed by ChatPanel — see
  // docs/tools.md for enabledTools, docs/multi-tenant.md for model/Ollama.
  const [safetyMode, setSafetyMode] = useState<SafetyMode>("readonly");
  const [chatMode, setChatMode] = useState<ChatMode>("ops");
  const [model, setModel] = useState<string | null>(null);
  const [enabledTools, setEnabledTools] = useState<string[] | null>(null);

  useEffect(() => {
    if (!activeTenantId) return;
    let cancelled = false;

    apiFetch("/api/ping")
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.text();
          setPing({ status: "error", message: `HTTP ${res.status} — ${body}` });
          return;
        }
        const body = await res.json();
        setPing({ status: "ok", tenant: body.tenant });
      })
      .catch((err) => {
        if (!cancelled) setPing({ status: "error", message: String(err) });
      });

    return () => {
      cancelled = true;
    };
  }, [activeTenantId]);

  // Switching tenant invalidates the chosen model and any tool restriction:
  // each tenant has its own Ollama and its own set of allowed tools (see
  // docs/multi-tenant.md, docs/tools.md). The reset goes through a
  // microtask (not a synchronous setState in the effect body) — same
  // convention as TenantProvider/ChatPanel elsewhere in this project.
  useEffect(() => {
    if (activeTenantId === null) return;
    Promise.resolve().then(() => {
      setModel(null);
      setEnabledTools(null);
    });
  }, [activeTenantId]);

  return (
    <div className="flex h-screen flex-col bg-aegis-bg font-sans text-aegis-text">
      <header className="flex flex-shrink-0 items-center justify-between border-b border-aegis-border px-6 py-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-aegis-text">Aegis</h1>
          <p className="text-xs text-aegis-dim">A private, multi-tenant conversational operations console.</p>
        </div>
        <div className="flex items-center gap-3">
          <TenantSelector />
          <div className="flex items-center gap-2 rounded-full border border-aegis-border bg-aegis-surface px-3 py-1.5 text-xs">
            <span
              className={
                "h-2 w-2 rounded-full " +
                (ping.status === "ok"
                  ? "bg-aegis-ok"
                  : ping.status === "error"
                    ? "bg-aegis-danger"
                    : "bg-aegis-warn animate-pulse")
              }
            />
            <span className="text-aegis-dim">
              {ping.status === "loading" && "Connecting…"}
              {ping.status === "ok" && `Connected — ${ping.tenant.name}`}
              {ping.status === "error" && `Unreachable: ${ping.message}`}
            </span>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <CollapsibleSidebar side="left" title="⚙️ Settings">
          <ModelSelector activeTenantId={activeTenantId} value={model} onChange={setModel} />

          <Panel eyebrow="Safety" category="settings" collapsible={false}>
            <SafetyModeBadge value={safetyMode} onChange={setSafetyMode} />
          </Panel>

          <ToolsPanel
            activeTenantId={activeTenantId}
            enabledTools={enabledTools}
            onChangeEnabledTools={setEnabledTools}
          />

          <ConfigPanel activeTenantId={activeTenantId} />

          <TenantAdminPanel />
        </CollapsibleSidebar>

        <main className="flex min-h-0 min-w-0 flex-1 items-start justify-center overflow-y-auto p-8">
          <ChatPanel safetyMode={safetyMode} chatMode={chatMode} model={model} enabledTools={enabledTools} />
        </main>

        <CollapsibleSidebar side="right" title="📚 RAG">
          <Segmented
            ariaLabel="Chat mode"
            value={chatMode}
            onChange={setChatMode}
            options={[
              { value: "ops", label: "Ops" },
              { value: "rag", label: "RAG" },
            ]}
          />

          <RagStatusPanel activeTenantId={activeTenantId} />
          <RagDocumentsPanel activeTenantId={activeTenantId} />
        </CollapsibleSidebar>
      </div>
    </div>
  );
}
