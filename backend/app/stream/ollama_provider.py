"""
Ollama provider — calls /api/chat with streaming and translates the raw
chunks into structured events consumed by app/agent/loop.py. This module
knows nothing about the AI SDK protocol (see app/stream/aisdk_protocol.py
for that) or the agent's logic (guardrails, tools...) — it only talks to
Ollama.
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator

import httpx

from app.stream.chunks import Chunk as OllamaChunk
from app.stream.chunks import ProviderError, TextChunk, ToolCall

DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.6:35b")

# Aliases kept for backward compatibility (existing call sites/tests refer
# to these Ollama-prefixed names) — same classes as the generic ones in
# app/stream/chunks.py, shared by every provider. See docs/llm-providers.md.
OllamaTextChunk = TextChunk
OllamaToolCall = ToolCall
OllamaError = ProviderError


async def stream_chat(
    messages: list[dict],
    tools: list[dict],
    model: str,
    ollama_url: str | None = None,
) -> AsyncGenerator[OllamaChunk, None]:
    """
    Streams a response from Ollama's /api/chat.

    `messages` in Ollama format: [{role, content}] and, for later turns,
    [{role: "assistant", content, tool_calls}] / [{role: "tool", content}].
    """
    base_url = ollama_url or DEFAULT_OLLAMA_URL
    tool_call_counter = 0

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{base_url}/api/chat",
                json={"model": model, "messages": messages, "tools": tools, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    try:
                        err = json.loads(body).get("error", body.decode(errors="replace"))
                    except Exception:
                        err = body.decode(errors="replace")
                    yield OllamaError(f"Ollama HTTP {resp.status_code}: {err}")
                    return

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        yield OllamaError(str(chunk["error"]))
                        return

                    msg = chunk.get("message", {})

                    for tc in msg.get("tool_calls", []) or []:
                        fn = tc.get("function", {})
                        raw_args = fn.get("arguments", {})
                        if isinstance(raw_args, str):
                            try:
                                raw_args = json.loads(raw_args)
                            except json.JSONDecodeError:
                                raw_args = {}
                        tool_call_counter += 1
                        # Ollama doesn't provide a stable id per tool call —
                        # we generate our own, reused for the input/output
                        # of the same call (required by the client-side AI
                        # SDK protocol).
                        yield OllamaToolCall(
                            id=f"call_{tool_call_counter}",
                            name=fn.get("name", ""),
                            arguments=raw_args,
                        )

                    content = msg.get("content", "")
                    if content:
                        yield OllamaTextChunk(content)

    except httpx.ConnectError:
        yield OllamaError(
            f"Ollama unreachable (`{base_url}`). Check that Ollama is running (`ollama serve`)."
        )
    except Exception as e:
        yield OllamaError(f"Ollama error: {type(e).__name__}: {e}")
