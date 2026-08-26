"""
AgentEvent → AI SDK UI Message Stream Protocol (SSE) encoder.

Format confirmed by reading `node_modules/ai/dist/index.js` (package `ai`
v7.0.79) rather than assumed from the docs — see docs/protocol.md for the
detail of that verification and its rationale:
- headers: see AISDK_STREAM_HEADERS below
- each event: `data: {json}\\n\\n`
- end of stream: `data: [DONE]\\n\\n`

This module is the ONLY layer that knows this format — app/agent/loop.py
knows nothing about it (see events.py). If the AI SDK protocol changes,
only this file needs to move.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

from app.agent import events as ev

AISDK_STREAM_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",
}


def _sse(chunk: dict) -> str:
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


async def encode_sse(events: AsyncGenerator[ev.AgentEvent, None]) -> AsyncGenerator[str, None]:
    """Translates a stream of AgentEvent into a stream of ready-to-send SSE lines."""
    async for event in events:
        for chunk in _to_chunks(event):
            yield _sse(chunk)
    yield "data: [DONE]\n\n"


def _to_chunks(event: ev.AgentEvent) -> list[dict]:
    """An AgentEvent can translate into several AI SDK chunks (e.g. start/delta/end for text)."""
    if isinstance(event, ev.Start):
        return [{"type": "start"}, {"type": "start-step"}]

    if isinstance(event, ev.TextStart):
        return [{"type": "text-start", "id": event.id}]

    if isinstance(event, ev.TextDelta):
        return [{"type": "text-delta", "id": event.id, "delta": event.delta}]

    if isinstance(event, ev.TextEnd):
        return [{"type": "text-end", "id": event.id}]

    if isinstance(event, ev.ToolInputAvailable):
        return [{
            "type": "tool-input-available",
            "toolCallId": event.tool_call_id,
            "toolName": event.tool_name,
            "input": event.input,
            # Our tools are defined server-side only (the client doesn't
            # know their schema ahead of time) → DynamicToolUIPart
            # client-side, see docs/protocol.md.
            "dynamic": True,
        }]

    if isinstance(event, ev.ToolOutputAvailable):
        return [{
            "type": "tool-output-available",
            "toolCallId": event.tool_call_id,
            "output": event.output,
        }]

    if isinstance(event, ev.ToolOutputError):
        return [{
            "type": "tool-output-error",
            "toolCallId": event.tool_call_id,
            "errorText": event.error_text,
        }]

    if isinstance(event, ev.ToolOutputDenied):
        return [{"type": "tool-output-denied", "toolCallId": event.tool_call_id}]

    if isinstance(event, ev.ApprovalRequired):
        return [{
            "type": "tool-approval-request",
            "approvalId": event.approval_id,
            "toolCallId": event.tool_call_id,
        }, {
            # Custom part: summary/category have no standard equivalent,
            # sent alongside so ConfirmCard (frontend) can display them.
            "type": "data-approval-details",
            "id": event.approval_id,
            "data": {"summary": event.summary, "category": event.category},
        }]

    if isinstance(event, ev.RagSources):
        return [{"type": "data-ragSources", "data": {"sources": event.sources}}]

    if isinstance(event, ev.ErrorEvent):
        return [{"type": "error", "errorText": event.error_text}]

    if isinstance(event, ev.Finish):
        return [{"type": "finish-step"}, {"type": "finish"}]

    raise TypeError(f"Unknown AgentEvent: {type(event)}")  # pragma: no cover
