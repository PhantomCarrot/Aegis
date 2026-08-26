# LLM providers

## What this is

Aegis talks to a chat-capable LLM to drive the agent loop (`app/agent/loop.py`), and separately to an embedding model for RAG (always Ollama — see below). Which one answers chat turns is a per-tenant choice, `llm.provider` in `config/tenants.yaml`, matching the same "each tenant picks its own" pattern as `exec.mode` (see [`multi-tenant.md`](multi-tenant.md)) — a consulting team could have one client on a shared Ollama, another on a local LM Studio instance, and a third being used to test a raw HF checkpoint through AirLLM, all in the same Aegis instance.

Three providers today:

| Provider | What it is | Native tool-calling |
|---|---|---|
| `ollama` (default) | Ollama's `/api/chat`, local or remote | Yes |
| `lmstudio` | LM Studio's local server (OpenAI-compatible) | Yes |
| `airllm` | An in-process Hugging Face model, no server involved | No — prompted (see below) |

```yaml
tenants:
  demo:
    # llm.provider absent → "ollama", using ollama.url below (same as today)
    ollama:
      url: "http://localhost:11434"

  lmstudio-tenant:
    llm:
      provider: lmstudio
      lmstudio:
        url: "http://localhost:1234"

  airllm-tenant:
    llm:
      provider: airllm
      airllm:
        model: "meta-llama/Llama-3.2-3B-Instruct"   # HF repo id or local path
        device: "cpu"                                 # or "cuda:0", etc.
        compression: null                              # "4bit" | "8bit" (needs bitsandbytes)
        max_new_tokens: 512
```

`ollama.url` stays separate from `llm.*` and is **always** used for RAG embeddings (`nomic-embed-text` via `/api/embed`, see [`rag.md`](rag.md)), regardless of which provider answers chat — embeddings aren't pluggable yet, only chat is. A tenant on `lmstudio` or `airllm` for chat still needs a reachable Ollama for RAG to work.

## Ollama

Unchanged from before this feature existed — `ollama.url`, `POST /api/chat`, streaming, native tool-calling. See [`multi-tenant.md`](multi-tenant.md).

## LM Studio

Start its local server first — `lms server start` (the CLI that ships with the app) or the app's own "Local Server" tab — then load a tool-calling-capable model (`lms load <model>`, or through the UI). Verified live against a real server for model discovery (`GET /v1/models`) and the chat-completions error path; the streaming + tool-call path is implemented against LM Studio's documented OpenAI-compatible contract (https://lmstudio.ai/docs/developer) but wasn't independently re-verified end to end for lack of a tool-calling model loaded at the time this was built.

Implementation note: LM Studio speaks OpenAI's chat-completions shape, which differs from Aegis's internal message format (the same one Ollama's `/api/chat` already expects) in two ways the provider translates on the way in and out:
- Tool call arguments stream as incremental JSON-string *fragments* across many chunks (keyed by array `index`), not one shot per call the way Ollama sends them — `app/stream/lmstudio_provider.py` accumulates them per index and parses once the turn's `finish_reason` arrives.
- Assistant tool calls and their results need explicit `id`/`tool_call_id` linkage that Aegis's internal format doesn't carry. Since `app/agent/loop.py` always emits a tool-result message immediately after its matching tool call, in order, the provider can safely synthesize ids and pair them positionally — see `_to_openai_messages()`.

## AirLLM

[AirLLM](https://github.com/lyogavin/airllm) runs a Hugging Face model in-process, streaming its weights layer by layer from disk — its whole point is fitting large models (its README mentions 70B on 4GB of VRAM) on modest hardware, at the cost of speed. Optional dependency, not installed by default:

```bash
cd backend
uv sync --extra airllm
```

This pulls in torch/transformers/accelerate — several GB — which is why it's opt-in rather than a base dependency everyone pays for.

**No native tool-calling.** AirLLM's entire surface is `AutoModel.from_pretrained(...).generate()` — a thin wrapper around `transformers`' own `generate()`, not a chat API, so there's no `tools` parameter to hand it the way Ollama and LM Studio take one. To keep tool-calling working the same way it does for the other two providers — Aegis's whole guardrail/confirmation flow sits on top of tool calls, so a text-only fallback would silently break every tenant that switches to this provider — `app/stream/airllm_provider.py` prompts the model itself:

1. The available tools (name, description, JSON Schema parameters) get folded into the system prompt, along with instructions to respond with a fixed delimited block to call one: `<tool_call>\n{"name": ..., "arguments": {...}}\n</tool_call>`.
2. The model's streamed output is scanned for that block as it's generated (`_scan_for_tool_calls()`), handling the tag arriving split across streamed pieces. Text outside the block streams normally; a well-formed block becomes a `ToolCall`, same as a native one from Ollama/LM Studio.
3. If the model doesn't follow the format exactly — no JSON, or an unterminated block — the raw text is surfaced rather than silently dropped ("fail open").

This is inherently less reliable than a model's own native tool-calling: it depends entirely on the model actually following the instructions, which varies by model and isn't guaranteed the way a purpose-built function-calling API is. It's the best available option for a library that's fundamentally `generate()`, not a chat server.

Model loading is cached in-process per `(model, device, compression)` — the whole reason AirLLM exists is to make loading a huge checkpoint bearable, so it's kept warm for the life of the backend process rather than reloaded on every turn. The first request against a given model pays the loading cost; later ones don't.

**Known gaps, not yet exercised end to end:**
- Not live-tested against a real model download in building this — the tag-scanning logic is unit-tested against synthetic text streams (`backend/tests/test_airllm_provider.py`), but a real generation run wasn't performed.
- Apple Silicon: `AutoModel.from_pretrained()` auto-dispatches to an MLX-backed implementation on macOS, which needs airllm's separate `mlx` extra — untested here.
- `device` accepts anything `transformers`/`torch` understand (`"cpu"`, `"cuda:0"`, ...); `"cpu"` is the safe default across machines but slow for anything beyond a small model.

## Choosing a model to actually run

`GET /api/llm/models` is provider-aware:
- `ollama` / `lmstudio`: queries the provider's live models endpoint (`/api/tags`, `/v1/models`) — same as before this feature, now generalized.
- `airllm`: returns the single model fixed in `llm.airllm.model` — there's nothing to discover at runtime, loading a different one on demand isn't a "pick from a dropdown" kind of operation given the cost.

The frontend's model selector (`ModelSelector.tsx`, in the Settings sidebar) reflects this — a real dropdown for Ollama/LM Studio, a fixed label for AirLLM.
