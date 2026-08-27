"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, lastAssistantMessageIsCompleteWithApprovalResponses } from "ai";
import { useMemo, useState } from "react";

import { ConfirmCard } from "@/components/chat/ConfirmCard";
import { RagSourcesFooter } from "@/components/chat/RagSourcesFooter";
import type { SafetyMode } from "@/components/chat/SafetyModeBadge";
import { ToolCallCard } from "@/components/chat/ToolCallCard";
import { getStoredTenantId } from "@/lib/api";

type ChatMode = "ops" | "rag";

/**
 * safetyMode/chatMode/model/enabledTools are now driven from the sidebars
 * (Settings on the left, RAG on the right — see app/page.tsx) instead of
 * internal state: ChatPanel just consumes these settings to build the
 * /api/chat request.
 */
export function ChatPanel({
  safetyMode,
  chatMode,
  model,
  enabledTools,
}: {
  safetyMode: SafetyMode;
  chatMode: ChatMode;
  model: string | null;
  enabledTools: string[] | null;
}) {
  const [input, setInput] = useState("");

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: "/api/backend/api/chat",
        headers: (): Record<string, string> => {
          const tenantId = getStoredTenantId();
          return tenantId ? { "X-Tenant-Id": tenantId } : {};
        },
        body: {
          safetyMode,
          mode: chatMode,
          ...(model ? { model } : {}),
          // null = no runtime restriction (see docs/tools.md) — omitted from
          // the body rather than sent explicitly as null.
          ...(enabledTools !== null ? { enabledTools } : {}),
        },
      }),
    [safetyMode, chatMode, model, enabledTools],
  );

  const { messages, sendMessage, addToolApprovalResponse, status, error } = useChat({
    transport,
    // Automatically resends the request once every pending approval on the
    // last message has been resolved — see docs/protocol.md.
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
  });

  const busy = status === "submitted" || status === "streaming";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    sendMessage({ text });
  };

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      <div className="flex min-h-[16rem] flex-col gap-3 rounded-lg border border-aegis-border bg-aegis-surface p-4">
        {messages.length === 0 && (
          <p className="text-sm text-aegis-dim">
            {chatMode === "rag"
              ? "RAG mode: answers are grounded in the indexed docs (see the RAG panel on the right)."
              : "Ask a question about your infra — e.g. « list pods in the default namespace »."}
          </p>
        )}
        {messages.map((message) => {
          const ragSourcesPart = message.parts.find(
            (p): p is typeof p & { type: "data-ragSources"; data: { sources: never[] } } =>
              p.type === "data-ragSources",
          );
          return (
            <div key={message.id} className="flex flex-col gap-2">
              <div className="text-[10px] uppercase tracking-wide text-aegis-faint">{message.role}</div>
              {message.parts.map((part, i) => {
                if (part.type === "text") {
                  return (
                    <p key={i} className="whitespace-pre-wrap text-sm text-aegis-text">
                      {part.text}
                    </p>
                  );
                }
                if (part.type === "dynamic-tool") {
                  if (part.state === "approval-requested") {
                    const detailsPart = message.parts.find(
                      (p): p is typeof p & { type: "data-approval-details"; id: string; data: { summary: string; category: string } } =>
                        p.type === "data-approval-details" && p.id === part.approval.id,
                    );
                    return (
                      <ConfirmCard
                        key={i}
                        toolName={part.toolName}
                        details={detailsPart?.data}
                        onRespond={(approved) =>
                          addToolApprovalResponse({ id: part.approval.id, approved })
                        }
                      />
                    );
                  }
                  return <ToolCallCard key={i} part={part} />;
                }
                return null;
              })}
              {ragSourcesPart && <RagSourcesFooter sources={ragSourcesPart.data.sources} />}
            </div>
          );
        })}
        {busy && <p className="text-xs text-aegis-faint">…</p>}
        {error && <p className="text-xs text-aegis-danger">{error.message}</p>}
      </div>

      <form onSubmit={submit} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Write a message…"
          disabled={busy}
          className="flex-1 rounded-md border border-aegis-border bg-aegis-surface px-3 py-2 text-sm text-aegis-text"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-aegis-accent px-4 py-2 text-sm font-semibold text-aegis-accent-ink disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
