# Aegis

**A private, multi-tenant conversational operations console — for teams who manage infrastructure across several clients or environments, and don't want their command history or secrets going through someone else's LLM.**

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Next.js 16](https://img.shields.io/badge/next.js-16-black?logo=nextdotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Ollama%20%7C%20LM%20Studio%20%7C%20AirLLM-2b2b2b)
![Qdrant](https://img.shields.io/badge/vector%20store-Qdrant-dc244c)
![Tests](https://img.shields.io/badge/backend%20tests-235%20passing-brightgreen)

Aegis isn't an autonomous "AI SRE" that fixes things on its own, and it isn't a single-cluster scanner — it's a copilot driven by a human operator, with explicit guardrails and an optional 100% local LLM. You ask it things in plain language ("what's crash-looping in the dev namespace", "list the ArgoCD apps out of sync"), it calls real tools against your real infra, and it never runs anything destructive without you saying yes first.

## Why this exists

- **Actually multi-tenant.** Not a single-cluster dashboard with a namespace filter — separate config, separate LLM provider, separate execution target, and a hard-isolated RAG index per tenant. Switch context instantly from the UI, no restart. Built for the shape of a consulting/platform team's day: several clients, several environments, one tool.
- **Secrets never reach the LLM in the clear.** An anonymizer intercepts every command result before it's sent anywhere — JWTs, connection strings, Key Vault values, kubectl `Secret` YAML — and swaps them for reversible placeholders that only live in backend memory for that turn. See [`docs/security-model.md`](docs/security-model.md) for a before/after example.
- **Nothing risky runs unattended.** Every command is classified `safe` / `mutant` / `destructive` and checked against one of three graduated modes (ReadOnly / Modify / Root). Anything short of read-only either gets refused outright or stops the conversation dead until you explicitly confirm it in the UI.
- **Bring your own LLM, including none of the cloud's business.** Ollama or LM Studio, local or remote, per tenant — or skip the server entirely and run a raw Hugging Face checkpoint in-process via AirLLM. Nothing about your infra has to leave your network. See [`docs/llm-providers.md`](docs/llm-providers.md).
- **The tool learns your infra instead of you writing docs for it.** RAG mode scrapes your live cluster, chunks and embeds it locally, and cites its sources — no stale runbook to keep in sync by hand.
- **You can see exactly what it's about to do.** Every tool call shows the exact command, where it actually ran (local machine or a named remote host, over SSH — including cert-based auth, see [`docs/execution-model.md`](docs/execution-model.md)), and the exact JSON schema the LLM was given to decide whether to call it. No black box.

## Quickstart

Prerequisites: Docker, Node 18+, [Ollama](https://ollama.com) (optional — auto-detected if present on `localhost:11434`). For RAG, the `nomic-embed-text` embedding model must be available (`ollama pull nomic-embed-text`).

```bash
cp .env.example .env
cp config/global.yaml.example config/global.yaml
cp config/tenants.yaml.example config/tenants.yaml

docker compose up -d        # backend + Qdrant

cd frontend
cp .env.example .env.local
npm install
npm run dev                 # → http://localhost:3000
```

That's it — the `demo` tenant is preconfigured and ready to talk to. Point it at your own cluster from **⚙️ Settings → 🗂️ Tenant administration** in the sidebar, or by editing `config/tenants.yaml` directly (see [`docs/multi-tenant.md`](docs/multi-tenant.md)).

### Backend in dev, without Docker

```bash
docker compose up -d qdrant  # RAG still needs Qdrant

# from the repo root (config paths are relative to cwd)
AEGIS_BACKEND_TOKENS=changeme-dev-token \
  uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8766
```

## How it fits together

Two services, deliberately never assumed to run on the same machine: a Next.js frontend you can deploy publicly (Vercel), and a self-hosted Python backend that stays close to the infrastructure it controls — because kubectl and cloud CLIs need real, persistent network access that a serverless function can't offer. The LLM only ever sees messages and returns text or a `tool_call` — it has no path to your infra; only the backend's Exec layer does, and every command passes through the guardrails first.

![Aegis architecture: a chat request flows from the browser through the Next.js proxy to the self-hosted backend, which loops with the LLM provider for tool calls but is the only component that ever executes a command — locally or over SSH to a configured host.](docs/assets/architecture-drawio.svg)

The browser never sees the backend's real URL or its auth token — both stay server-side in the Next.js proxy. Full walkthrough, numbered step by step, in [`docs/architecture.md`](docs/architecture.md).

## What's in the box

| Area | What it does |
|---|---|
| **Chat agent** | Streaming multi-turn tool-calling loop, hand-implemented AI SDK protocol on the Python side — see [`docs/protocol.md`](docs/protocol.md) |
| **LLM providers** | Ollama, LM Studio, or an in-process Hugging Face model via AirLLM, picked per tenant — see [`docs/llm-providers.md`](docs/llm-providers.md) |
| **Tools** | `kubectl` (get/describe/logs), ArgoCD (app list/status), a generic cloud CLI wrapper (Azure `az` in V1, read-only), and a guarded arbitrary shell command — see [`docs/tools.md`](docs/tools.md) |
| **Guardrails** | 3 safety modes × 3 command categories, human confirmation flow using the AI SDK's native tool-approval mechanism — see [`docs/security-model.md`](docs/security-model.md) |
| **Secret anonymization** | Automatic, before anything reaches the LLM — see [`docs/security-model.md`](docs/security-model.md) |
| **Multi-tenant** | Isolated config, LLM provider, execution target, and RAG index per tenant; hot-reloaded, no restart to add a client — see [`docs/multi-tenant.md`](docs/multi-tenant.md) |
| **Execution model** | Local subprocess or remote SSH per tenant, including short-lived certificate auth (Azure AD, and the same idea for AWS/GCP) — see [`docs/execution-model.md`](docs/execution-model.md) |
| **RAG** | Live-infra scraping → heading-aware chunking → local Ollama embeddings → Qdrant, cited in chat answers, browsable from the UI — see [`docs/rag.md`](docs/rag.md) |
| **Transparency** | Inspect the resolved tenant config, where each command actually ran, and the exact tool schema shown to the LLM, all from the UI — see [`docs/tools.md`](docs/tools.md) and [`docs/execution-model.md`](docs/execution-model.md) |

## Documentation

Every doc opens with a short "what this is / why it exists" before the detail — meant to be readable without already knowing the codebase.

| Doc | Covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System overview, the frontend/backend split, network auth, backend/frontend module layout |
| [`docs/multi-tenant.md`](docs/multi-tenant.md) | The tenant model, config format, hot-reload, how the active tenant is resolved per request |
| [`docs/llm-providers.md`](docs/llm-providers.md) | Ollama, LM Studio, and AirLLM as chat backends — per-tenant, with AirLLM's prompted tool-calling explained |
| [`docs/security-model.md`](docs/security-model.md) | Safety modes, guardrail classification, the confirmation flow, secret anonymization, audit logging |
| [`docs/execution-model.md`](docs/execution-model.md) | Local vs. SSH execution, certificate-based auth walkthroughs for Azure/AWS/GCP and a plain local VM |
| [`docs/tools.md`](docs/tools.md) | The tool registry, per-tenant activation, the runtime on/off toggle, inspecting the LLM-facing schema |
| [`docs/rag.md`](docs/rag.md) | The full RAG pipeline — scraping, chunking, embeddings, storage, search, citations |
| [`docs/protocol.md`](docs/protocol.md) | How the backend implements the Vercel AI SDK streaming protocol in Python (no official SDK for it) |
| [`docs/deployment.md`](docs/deployment.md) | Exposing the backend (Cloudflare Tunnel) and deploying the frontend (Vercel) |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records — the why behind the bigger calls |

## Known gaps

Dense-only RAG search (no hybrid search or reranking yet), kubectl is the only RAG source (no Terraform scraper or LLM-narrated docs), and no object storage / streaming / observability / CI-CD tools yet — see [`docs/rag.md`](docs/rag.md#not-yet-implemented) for the full list. [`docs/adr/`](docs/adr/) has the reasoning behind the bigger design calls (why a Python backend + Next.js frontend, why the confirmation flow rides on the AI SDK's native approval mechanism, ...).

## Contributing

Issues and PRs welcome — the docs above are written to make that possible without a guided tour of the codebase first. If you're adding a tool, [`docs/tools.md`](docs/tools.md) and the existing `backend/app/agent/tools/*.py` modules are the fastest way in; if you're touching the streaming protocol, read [`docs/protocol.md`](docs/protocol.md) first, it explains a couple of non-obvious constraints the client enforces.

## License

To be decided before publication.
