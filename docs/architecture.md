# Architecture

## What this is

Aegis is made of two services that never run on the same machine by default:

- a **frontend** (Next.js) meant to be deployed on Vercel — the interface you open in your browser;
- a **self-hosted execution backend** (FastAPI, Python), which runs close to the infrastructure it controls — locally on your machine, or on a remote machine with network access to the cluster/cloud (see [`execution-model.md`](execution-model.md)).

This separation exists because the frontend needs to be hostable anywhere (including publicly, on Vercel), while the backend needs permanent network access to your infra (kubectl, cloud CLI, etc.) — something a standard serverless function can't offer.

## Overview

![Aegis architecture: a chat request flows from the browser through the Next.js proxy to the self-hosted backend, which loops with the LLM provider for tool calls but is the only component that ever executes a command — locally or over SSH to a configured host.](assets/architecture.svg)

The numbered flow in one pass: **1–2** the browser's request reaches the backend through the frontend's proxy, which is the only thing that ever holds the bearer token. **3–4** the agent loop sends the conversation and tool schemas to whichever LLM provider the tenant is configured for ([`llm-providers.md`](llm-providers.md)); the LLM only ever replies with text or a `tool_call` — it has no path to your infrastructure. **5–6** a tool call is checked against the active safety mode before Exec runs anything, and its result is anonymized before it goes anywhere near the LLM again ([`security-model.md`](security-model.md)). **7** the loop repeats — steps 3–7 — until the LLM has enough to answer. **8** the final answer streams back the way it came.

The teal arrows between the agent loop and Qdrant are unnumbered on purpose: they only fire when RAG mode is on for that turn, running alongside the tool-calling steps above rather than as one more link in the same chain — see [`rag.md`](rag.md) for the full retrieval pipeline.

**Why a frontend-side proxy instead of a direct browser → backend call?** The browser must never know the backend's real URL or the token that authenticates it — both would otherwise be visible in the DevTools of any visitor to the page. The frontend therefore exposes `/api/backend/*` ([`app/api/backend/[...path]/route.ts`](../frontend/app/api/backend/%5B...path%5D/route.ts)), a Route Handler that runs on the Next.js server, reads `AEGIS_BACKEND_URL`/`AEGIS_BACKEND_TOKEN` (never prefixed `NEXT_PUBLIC_*`, so never sent to the browser) and forwards the request.

## Network authentication

Since the backend is potentially reachable from the internet (frontend hosted on Vercel), two independent layers protect it:

1. **Transport**: the backend never opens a public port directly — it exposes itself via an outgoing tunnel (Cloudflare Tunnel), so there's no inbound port to filter.
2. **Application**: every request must carry a valid bearer token (see [`backend/app/security/auth.py`](../backend/app/security/auth.py)), verified in constant time. Good enough for single-user usage — no account/role concept in V1.

## Current status (M7 — V1 complete)

- **M0**: end-to-end chain — `/healthz` (public) and `/api/ping` (token-protected) on the backend, a frontend home page that checks the connection through the proxy.
- **M1**: multi-tenant config (`config/tenants.yaml`, hot-reload) + local/SSH execution abstraction — see [`multi-tenant.md`](multi-tenant.md) and [`execution-model.md`](execution-model.md). `/api/ping` resolves the active tenant from `X-Tenant-Id`, `TenantSelector` (frontend) lets you switch between tenants.
- **M2**: conversational agent — `POST /api/chat` (`app/routers/chat.py`) drives the tool-calling loop (`app/agent/loop.py`) against Ollama, with the first tool (`kubectl_get`), the secret anonymizer, and the guardrails ported with tests. Streaming to the frontend follows the AI SDK UI Message Stream Protocol, hand-implemented on the Python side (`app/stream/aisdk_protocol.py`) — see [`protocol.md`](protocol.md). `ChatPanel` (frontend, `@ai-sdk/react`) consumes this stream through the proxy, fixed to stream instead of buffering.
- **M3**: full confirmation flow — a second tool (`run_command`, classified dynamically by the guardrails), the `ApprovalRequired` → `tool-approval-request`/`data-approval-details` → `ConfirmCard` (frontend) → `addToolApprovalResponse` → automatic resubmission → actual execution or denial branching on the backend. Uses the Vercel AI SDK's native approval mechanism rather than a custom protocol (see [ADR 0002](adr/0002-native-tool-approval-instead-of-custom-confirmation.md)). `SafetyModeBadge` lets you change modes from the UI. Full detail in [`security-model.md`](security-model.md).

- **M4**: read-tool parity (all always-safe, no guardrail) — `kubectl_describe`, `kubectl_logs`, `argocd_app_list`/`argocd_app_status` (via `kubectl get applications`, no dependency on the dedicated `argocd` CLI), `cloud_cli` (Azure `az` CLI in V1, read-only enforced by the tool itself — list/show/get/describe only). Tools available in total: `kubectl_get/describe/logs`, `argocd_app_list/status`, `cloud_cli`, `run_command` (guarded).
- **M5**: full RAG pipeline — doc generation via scraping (`app/rag/docs_gen.py`), heading-structure chunking (`app/rag/chunking.py`), 100% local embeddings via Ollama (`app/rag/embeddings.py`), Qdrant storage with one collection per tenant (`app/rag/store.py`), search + citations (`app/rag/context.py`). RAG mode in the chat (Ops/RAG toggle in the UI), `POST /api/rag/generate` and `GET /api/rag/status` endpoints. Full detail in [`rag.md`](rag.md).
- **M6**: hardening — CORS tightened to a configurable allowlist (`AEGIS_ALLOWED_ORIGINS`, no more wildcard), structured logging + guardrail decision audit trail (`app/logging_config.py`, see [`security-model.md`](security-model.md#audit)), automatic Ollama detection at startup, optional `known_hosts_path` to pin SSH host keys (see [`execution-model.md`](execution-model.md)). Deployment guide (Cloudflare Tunnel + Vercel) in [`deployment.md`](deployment.md) — manual steps, requiring the operator's own accounts.
- **M7**: full documentation review — fixed sections that had gone stale across milestones (`protocol.md` and `multi-tenant.md` still referenced some milestones as "upcoming" even though they were done), verified all internal links resolve to real files, added a `known_hosts_path` example to `config/tenants.yaml.example`.

That's the end of the V1 scope as planned — see [ADR 0001](adr/0001-python-backend-nextjs-frontend-split.md) and [ADR 0002](adr/0002-native-tool-approval-instead-of-custom-confirmation.md) for the architecture decisions that shaped these seven milestones, and the "Deferred" sections of [`rag.md`](rag.md) for what's next (V1.1).
