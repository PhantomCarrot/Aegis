# Architecture

## What this is

Aegis is made of two services that never run on the same machine by default:

- a **frontend** (Next.js) meant to be deployed on Vercel — the interface you open in your browser;
- a **self-hosted execution backend** (FastAPI, Python), which runs close to the infrastructure it controls — locally on your machine, or on a remote machine with network access to the cluster/cloud (see [`execution-model.md`](execution-model.md)).

This separation exists because the frontend needs to be hostable anywhere (including publicly, on Vercel), while the backend needs permanent network access to your infra (kubectl, cloud CLI, etc.) — something a standard serverless function can't offer.

## Overview

![Aegis architecture: a chat request flows from the browser through the Next.js proxy to the self-hosted backend, which loops with the LLM provider for tool calls but is the only component that ever executes a command — locally or over SSH to a configured host.](assets/architecture-drawio.svg)

The numbered flow in one pass: **1–2** the browser's request reaches the backend through the frontend's proxy, which is the only thing that ever holds the bearer token. **3–4** the agent loop sends the conversation and tool schemas to whichever LLM provider the tenant is configured for ([`llm-providers.md`](llm-providers.md)); the LLM only ever replies with text or a `tool_call` — it has no path to your infrastructure. **5–6** a tool call is checked against the active safety mode before Exec runs anything, and its result is anonymized before it goes anywhere near the LLM again ([`security-model.md`](security-model.md)). **7** the loop repeats — steps 3–7 — until the LLM has enough to answer. **8** the final answer streams back the way it came.

The teal arrows between the agent loop and Qdrant are unnumbered on purpose: they only fire when RAG mode is on for that turn, running alongside the tool-calling steps above rather than as one more link in the same chain — see [`rag.md`](rag.md) for the full retrieval pipeline.

**Why a frontend-side proxy instead of a direct browser → backend call?** The browser must never know the backend's real URL or the token that authenticates it — both would otherwise be visible in the DevTools of any visitor to the page. The frontend therefore exposes `/api/backend/*` ([`app/api/backend/[...path]/route.ts`](../frontend/app/api/backend/%5B...path%5D/route.ts)), a Route Handler that runs on the Next.js server, reads `AEGIS_BACKEND_URL`/`AEGIS_BACKEND_TOKEN` (never prefixed `NEXT_PUBLIC_*`, so never sent to the browser) and forwards the request.

## Network authentication

Since the backend is potentially reachable from the internet (frontend hosted on Vercel), two independent layers protect it:

1. **Transport**: the backend never opens a public port directly — it exposes itself via an outgoing tunnel (Cloudflare Tunnel), so there's no inbound port to filter.
2. **Application**: every request must carry a valid bearer token (see [`backend/app/security/auth.py`](../backend/app/security/auth.py)), verified in constant time. Good enough for single-user usage — there's no account/role concept.

## Backend module layout

| Module | What lives there |
|---|---|
| `app/config/` | Tenant + global config loading and hot-reload (`tenants.py`), the config schema (`schema.py`) |
| `app/security/` | Bearer token auth (`auth.py`) |
| `app/exec/` | Command execution abstraction — `base.py` (interface), `local.py` (subprocess), `ssh.py` (remote, via `asyncssh`) — see [`execution-model.md`](execution-model.md) |
| `app/agent/` | The tool-calling loop (`loop.py`), internal events (`events.py`), the secret anonymizer (`anonymizer.py`), command guardrails (`guardrails.py`), the system prompt (`prompt.py`), and the tool implementations (`tools/`) |
| `app/stream/` | LLM provider implementations (`ollama_provider.py`, `lmstudio_provider.py`, `airllm_provider.py`) behind a common dispatcher (`providers.py`), plus the AI SDK streaming-protocol encoder (`aisdk_protocol.py`) — see [`llm-providers.md`](llm-providers.md) and [`protocol.md`](protocol.md) |
| `app/rag/` | The RAG pipeline — scraping (`docs_gen.py`), chunking (`chunking.py`), embeddings (`embeddings.py`), Qdrant storage (`store.py`), search + citations (`context.py`) — see [`rag.md`](rag.md) |
| `app/routers/` | The HTTP surface — `chat.py`, `tenants.py`, `tools.py`, `rag.py`, `llm.py`, `health.py` |

The agent loop, the provider dispatcher, and the AI SDK encoder each know nothing about the other two's internals — `loop.py` yields provider-agnostic events, `aisdk_protocol.py` is the only place that translates them into the wire format (see [`protocol.md`](protocol.md#separation-of-concerns)), and swapping a tenant's LLM provider never touches either.

## Frontend layout

`components/chat/` holds the conversation UI (`ChatPanel`, `ToolCallCard`, `ConfirmCard`, `SafetyModeBadge`, `RagSourcesFooter`); `components/sidebar/` holds the per-tenant controls (`TenantSelector`, `ModelSelector`, `ConfigPanel`, `ToolsPanel`, `RagDocumentsPanel`, `RagStatusPanel`). Shared tenant state lives in `hooks/useTenant.tsx`; the typed API client is in `lib/api.ts`.

See [ADR 0001](adr/0001-python-backend-nextjs-frontend-split.md) and [ADR 0002](adr/0002-native-tool-approval-instead-of-custom-confirmation.md) for the reasoning behind the frontend/backend split and the confirmation-flow design, and [`rag.md`](rag.md#not-yet-implemented) for what isn't built yet.
