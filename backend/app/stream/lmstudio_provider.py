"""
LM Studio provider — calls its local server (`lms server start`, or the
app's own "Local Server" tab), which speaks the OpenAI-compatible chat-
completions API. Verified live against a real LM Studio server for
`GET /v1/models` (see app/routers/llm.py); the chat-completions streaming
shape below follows the standard OpenAI protocol LM Studio documents
itself against (https://lmstudio.ai/docs/developer) — not independently
re-verified here for lack of a tool-calling-capable model loaded locally
at the time.
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator

import httpx

from app.stream.chunks import ProviderError, TextChunk, ToolCall

DEFAULT_LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://localhost:1234")


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """
    Translates Aegis's internal message shape — the same one Ollama's
    /api/chat already expects, used as the lingua franca between
    app/agent/loop.py and every provider (see docs/llm-providers.md) —
    into OpenAI's. The two differ in how a tool call round-trips through
    history:

    - Internal/Ollama: assistant `tool_calls: [{"function": {"name",
      "arguments": dict}}]` (no id), followed by plain `{"role": "tool",
      "content": ...}` results — no explicit linkage, request order is
      enough.
    - OpenAI: assistant `tool_calls: [{"id", "type": "function",
      "function": {"name", "arguments": "<json string>"}}]`, and each tool
      result needs a matching `tool_call_id`.

    loop.py always emits a `tool` message immediately per matching
    `tool_calls` entry, in the same order — so synthesizing ids here and
    pairing them positionally is safe; it mirrors exactly how the history
    was built, not a guess.
    """
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            ids = [f"call_{i}_{j}" for j in range(len(msg["tool_calls"]))]
            out.append({
                "role": "assistant",
                "content": msg.get("content") or None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": json.dumps(tc["function"]["arguments"]),
                        },
                    }
                    for call_id, tc in zip(ids, msg["tool_calls"])
                ],
            })
            i += 1
            for call_id in ids:
                if i < len(messages) and messages[i].get("role") == "tool":
                    out.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": messages[i].get("content", ""),
                    })
                    i += 1
            continue
        out.append({"role": msg["role"], "content": msg.get("content", "")})
        i += 1
    return out


async def stream_chat(
    messages: list[dict],
    tools: list[dict],
    model: str,
    base_url: str | None = None,
) -> AsyncGenerator[TextChunk | ToolCall | ProviderError, None]:
    """Streams a response from LM Studio's /v1/chat/completions."""
    url = (base_url or DEFAULT_LMSTUDIO_URL).rstrip("/")
    openai_messages = _to_openai_messages(messages)

    # Accumulates streamed tool-call fragments by their position in the
    # response's tool_calls array (`index`) — OpenAI-style streaming sends
    # `function.arguments` as incremental string fragments across many
    # chunks, not one shot the way Ollama's /api/chat does.
    pending_calls: dict[int, dict] = {}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": openai_messages,
                    "tools": tools,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    try:
                        parsed = json.loads(body)
                        err_field = parsed.get("error", body.decode(errors="replace"))
                        # LM Studio's error body nests the human message
                        # under error.message (verified against a real
                        # server, e.g. "No models loaded...") rather than
                        # error being a plain string.
                        err = err_field.get("message", err_field) if isinstance(err_field, dict) else err_field
                    except Exception:
                        err = body.decode(errors="replace")
                    yield ProviderError(f"LM Studio HTTP {resp.status_code}: {err}")
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        entry = pending_calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                        if tc_delta.get("id"):
                            entry["id"] = tc_delta["id"]
                        fn_delta = tc_delta.get("function") or {}
                        if fn_delta.get("name"):
                            entry["name"] += fn_delta["name"]
                        if fn_delta.get("arguments"):
                            entry["arguments"] += fn_delta["arguments"]

                    content = delta.get("content")
                    if content:
                        yield TextChunk(content)

                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason and pending_calls:
                        for idx in sorted(pending_calls):
                            entry = pending_calls[idx]
                            try:
                                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                            except json.JSONDecodeError:
                                args = {}
                            yield ToolCall(
                                id=entry["id"] or f"call_{idx}",
                                name=entry["name"],
                                arguments=args,
                            )
                        pending_calls = {}

    except httpx.ConnectError:
        yield ProviderError(
            f"LM Studio unreachable (`{url}`). Check that its local server is running "
            f'(`lms server start`, or the app\'s "Local Server" tab).'
        )
    except Exception as e:
        yield ProviderError(f"LM Studio error: {type(e).__name__}: {e}")
