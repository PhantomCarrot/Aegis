# Living documentation & RAG

## What this is

Rather than depending on pre-existing external documentation (often missing or stale), Aegis generates its own documentation by scraping the active tenant's real infrastructure, indexes it in a vector database, and uses it to enrich its answers with source citations — a full RAG (Retrieval-Augmented Generation) pipeline, with embeddings computed locally (no dependency on a cloud API). Search is hybrid (dense + sparse, fused with Reciprocal Rank Fusion) and retrieved text is anonymized before it ever reaches the LLM, same as tool results — see [Anonymization at retrieval time](#anonymization-at-retrieval-time).

## Full pipeline

![Aegis RAG pipeline: docs_gen.py scrapes the cluster into a Markdown doc, chunking.py splits it, dense and sparse embeddings are computed and stored in Qdrant via store.py. On a RAG-mode chat turn, the question is embedded the same two ways, store.py runs a hybrid dense+sparse search fused with RRF, anonymizer.py redacts secrets from the retrieved text, and context.py builds the cited context injected into the system prompt.](assets/rag-drawio.svg)

Two flows, each triggered independently: **generation + indexing** (top) runs once per `POST /api/rag/generate` call — scrape, chunk, embed both ways, upsert to Qdrant. **Search** (bottom) runs on every chat turn in RAG mode — embed the question, hybrid-search Qdrant, anonymize what came back, build the cited context. Neither flow touches the other except through the Qdrant collection itself.

1. **Generation** (`app/rag/docs_gen.py`, `app/rag/terraform_gen.py`): scrapes kubectl (namespaces, pods, deployments, services) on the active tenant's cluster, always, producing `cluster-overview.md`. If the tenant has `terraform_dir` configured, also runs `terraform show -json` there and produces a second document, `terraform-state.md` — one section per resource (its full `address`, e.g. `module.aks.azurerm_kubernetes_cluster.main`, recursing into nested modules), with its type/provider and attribute values. Both are indexed from the same `POST /api/rag/generate` call, as two independent documents (own `source_path`) — no LLM narrative generation yet (see [below](#not-yet-implemented)).
2. **Chunking** (`app/rag/chunking.py`): splits by heading structure rather than a blind sliding window — each chunk is prefixed with its "breadcrumb" (e.g. `Cluster > Pods`) so the hierarchical context isn't lost once isolated. A section too long for one chunk is re-split with a sliding window whose cut points back off to the nearest space/newline (`_backoff_to_boundary`), so a chunk never starts or ends mid-word.
3. **Embeddings** (`app/rag/embeddings.py`, `app/rag/sparse_embeddings.py`): every chunk gets both a **dense** vector — 100% local via Ollama (`POST /api/embed`), `nomic-embed-text` by default (768 dimensions) — and a **sparse** (BM25-style keyword) vector via [`fastembed`](https://github.com/qdrant/fastembed) (`Qdrant/bm25`, local ONNX runtime, no torch/API dependency). Dense embeddings are independent of `tenant.llm.provider` — they always go through Ollama, even for a tenant whose chat LLM is LM Studio or AirLLM, since neither exposes an embeddings endpoint; `tenant.ollama.url` still needs to point at a real Ollama instance in that case (see [`llm-providers.md`](llm-providers.md#what-this-is)). Sparse embeddings need no network at all after the model's one-time download.
4. **Storage** (`app/rag/store.py`): one Qdrant collection per tenant (`aegis_{tenant_id}`) — hard isolation, no shared `tenant_id` filter that could leak on a bug. Each point carries named `dense`/`sparse` vectors plus a `generated_at` timestamp. Deterministic point IDs (UUID5 derived from tenant+source+chunk index): re-indexing a source cleanly overwrites its old chunks without duplicating them. A collection created before hybrid search existed (single anonymous vector) is detected and silently dropped + recreated the next time it's written to — RAG data is 100% derived from live infra, so there's nothing worth migrating in place. `QDRANT_URL` isn't limited to the local container the docker-compose quickstart bundles — point it at any reachable Qdrant, including a managed/remote instance (e.g. Qdrant Cloud), and set `QDRANT_API_KEY` if that instance requires one.
5. **Search** (`app/rag/context.py`, `app/rag/store.py`): in the chat's RAG mode, the user's last question is embedded both ways (dense + sparse) and searched with Qdrant's `prefetch` + `FusionQuery(fusion=Fusion.RRF)` — each side contributes candidates, Reciprocal Rank Fusion merges them into one ranking. This catches both semantic matches (dense) and exact keyword/identifier matches (sparse) that dense alone can miss — a namespace name or resource kind carries little semantic weight but matters a lot in infra docs. Results below `SCORE_THRESHOLD` are dropped; the retrieved text is anonymized (see next section), formatted with numbered citations, and injected into the system prompt.

## Anonymization at retrieval time

Indexed content is scraped straight from live infra (`docs_gen.py`) and can contain the same kinds of secrets a tool result can — a token embedded in a `kubectl describe`, a connection string. Retrieved chunks are redacted through the same per-chat-turn `Anonymizer` already used for tool results (`app/agent/anonymizer.py`'s `anonymize_text`), right before injection into the prompt — **not** at indexing time. Anonymizing at indexing time would make a placeholder unreversible for a later turn (the `Anonymizer` instance from that `generate()` call no longer exists by then), and would redact `GET /api/rag/documents` too, the "browse indexed content" view meant to stay in clear text for the authenticated operator inspecting their own infra. A secret already anonymized elsewhere this turn (a tool result) gets the same placeholder here, since both share one `Anonymizer` instance — see [`security-model.md`](security-model.md#anonymization). Skipped in `root`/`__confirmed__` safety mode, same rule as tool results.

## Observability

RAG search and generation are traced through the same audit logger used for guardrail decisions (`aegis.audit`, see [`security-model.md`](security-model.md)) — no new logging system, just two more event kinds:
- `rag_search` — `tenant`, `hits`, `top_score`, `query_chars` (the question's length, never its content).
- `rag_generate` — `tenant`, `ok`, `chunks_indexed`, `duration_ms`.

## Freshness

Every chunk from one `generate()` call carries the same `generated_at` (ISO UTC) timestamp. `GET /api/rag/status` and the response of `POST /api/rag/generate` surface it, and the sidebar's **Index status** panel shows a relative time (`"4 chunks indexed · generated 3m ago"`). There's no scheduler — generation stays a deliberate, manual action (**Generate** button or `POST /api/rag/generate`), consistent with a tool meant to be driven by an operator rather than run unattended; the freshness indicator exists so that choice is visible, not hidden.

## Usage

In the UI, the RAG panel (sidebar): the **Generate** button triggers scraping + indexing for the active tenant, **Index status** shows the chunk count and freshness (`"N chunks indexed (2 documents)"` once Terraform state is also indexed). The **Ops / RAG** toggle in the chat switches between normal mode (tools only) and RAG mode (documentation context injected on top of the tools — both can combine, the LLM keeps access to its tools even in RAG mode).

Terraform state scraping is opt-in per tenant: set `terraform_dir` in `config/tenants.yaml` to the directory containing that tenant's already-initialized Terraform config (`terraform init` already run, backend already configured — Aegis doesn't provision or configure Terraform itself, only reads its state). On `exec.mode: local`, `~` is expanded against the machine running the backend; on `exec.mode: ssh`, the path is used as-is on the remote host, same limitation `kubeconfig_dir` already has (no local-to-remote path translation). Leave it unset to skip Terraform entirely — most tenants will.

A second panel, **Indexed content (RAG)**, lets you browse directly what's been indexed — documents grouped, expandable chunks with their breadcrumb and full text (`RagDocumentsPanel.tsx`), shown unredacted (see [Anonymization at retrieval time](#anonymization-at-retrieval-time)): no need to guess what RAG mode "sees", you can read it yourself.

On the API side:
- `POST /api/rag/generate` — scrapes + indexes for the active tenant (resolved via `X-Tenant-Id`), returns `{ok, documents: [{source_path, chunks_indexed, chars, generated_at}, ...], generated_at}` — one entry per document generated (`cluster-overview.md` always, `terraform-state.md` too if `terraform_dir` is set); the top-level `generated_at` is the last document's timestamp
- `GET /api/rag/status` — `{ready, points_count, generated_at}` for the active tenant
- `GET /api/rag/documents` — indexed content grouped by document (`{documents: [{source_path, chunk_count, chunks: [...]}]}`), for browsing/debugging
- `POST /api/chat` with `{"mode": "rag", ...}` — enriches the system prompt with the retrieved (anonymized) context, emits a `data-ragSources` part (citations) before the response text

## Cited sources — real example

Question: *"Briefly, what does the RAG context say about namespaces?"* — against a tenant with no real cluster reachable (every scraped section is a kubectl error), so ranking is driven purely by which chunk best matches "namespaces":

```json
{
  "sources": [
    {"index": 1, "source_path": "cluster-overview.md", "heading_path": "... > Namespaces", "score": 1.0},
    {"index": 2, "source_path": "cluster-overview.md", "heading_path": "... > Pods", "score": 0.333},
    {"index": 3, "source_path": "cluster-overview.md", "heading_path": "... > Services", "score": 0.25},
    {"index": 4, "source_path": "cluster-overview.md", "heading_path": "... > Deployments", "score": 0.2}
  ]
}
```

The "Namespaces" chunk comes out on top for a question about namespaces — hybrid search works as expected (verified under real conditions, not just in tests). Note the score scale: these are RRF-fused ranks, not raw cosine similarity — a hit found at rank 0 by both dense and sparse search caps out around `2/61 ≈ 0.033` with Qdrant's default RRF constant, so `SCORE_THRESHOLD` and any score you log or display should be read as "rank quality", not "percent similarity".

## Not yet implemented

- **Cross-encoder reranking** on top of the current hybrid (dense+sparse) retrieval — worthwhile once the corpus is large enough to justify a second model pass and its latency; today's index (one or two auto-generated docs per tenant) doesn't need it yet.
- **LLM narrative doc generation** — both scrapers produce mechanically-formatted Markdown, not LLM-written prose.
- **Local sources** (indexing existing Markdown files alongside the auto-generated docs).
