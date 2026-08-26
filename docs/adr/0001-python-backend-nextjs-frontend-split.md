# ADR 0001 — Self-hosted Python backend + Next.js frontend deployable on Vercel

## Status
Accepted

## Context
Aegis needs to run real commands (kubectl, cloud CLI…) against infrastructure that sometimes requires permanent network access (VPN, internal network). A serverless function (Vercel) is by nature ephemeral and has no persistent network state — incompatible with this usage. The frontend, on the other hand, needs no special network access and benefits from a modern deployment (Vercel, AI SDK).

The existing business logic (tool-calling loop, guardrails, secret anonymizer) is already written and battle-tested in Python.

## Decision
The frontend (Next.js) is deployable on Vercel. The execution backend stays in Python/FastAPI, self-hosted (local or a remote machine depending on the tenant), and itself implements the streaming protocol expected by the Vercel AI SDK on the frontend.

## Consequences
- Two languages in the repo instead of a unified TypeScript stack — accepted in exchange for reusing already-tested Python code and the fact that running system commands is more natural in Python.
- The AI SDK protocol has to be manually reimplemented on the Python side (no official SDK) — an explicit technical risk, treated as a priority spike (see the implementation plan, milestone M2, and [`protocol.md`](../protocol.md)).
- The backend needs a network exposure layer (Cloudflare Tunnel) and application-level auth (bearer token) since it may be reachable from a publicly hosted frontend.
