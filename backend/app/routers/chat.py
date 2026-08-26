"""POST /api/chat — endpoint consumed by useChat (Vercel AI SDK) on the frontend."""
from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agent.loop import PendingApproval, run_agent_loop
from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.rag.context import build_context
from app.rag.embeddings import EmbeddingError
from app.rag.store import get_store
from app.security.auth import RequireAuth
from app.stream.aisdk_protocol import AISDK_STREAM_HEADERS, encode_sse

router = APIRouter(prefix="/api", tags=["chat"], dependencies=[RequireAuth])

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.6:35b")


def _extract_text(parts: list[dict]) -> str:
    """
    Concatenates the 'text' parts of a UIMessage.

    Known limitation (V1): already-resolved 'dynamic-tool' parts
    (output-available) from previous turns aren't reconstructed into the
    Ollama history — only the text the assistant wrote about them is kept.
    The only 'dynamic-tool' part actually handled is the one pending
    confirmation (see _find_pending_approval), which covers milestone M3's
    needs.
    """
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def _ui_messages_to_ollama_history(messages: list[dict]) -> list[dict]:
    history = []
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _extract_text(msg.get("parts", []))
        if text:
            history.append({"role": role, "content": text})
    return history


def _find_pending_approval(messages: list[dict]) -> PendingApproval | None:
    """
    Looks, in the last assistant message, for a dynamic-tool part in
    "approval-responded" state — the signal that the user just responded
    to a confirmation (ConfirmCard on the frontend) and the tool now needs
    to actually run. See docs/security-model.md and ADR 0002.
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        for part in msg.get("parts", []):
            if part.get("type") == "dynamic-tool" and part.get("state") == "approval-responded":
                approval = part.get("approval") or {}
                return PendingApproval(
                    tool_call_id=part["toolCallId"],
                    tool_name=part["toolName"],
                    input=part.get("input") or {},
                    approved=bool(approval.get("approved")),
                    reason=approval.get("reason"),
                )
        break  # only the LAST assistant message matters
    return None


@router.post("/chat")
async def chat(
    request: Request,
    tenant: Annotated[TenantConfig, Depends(resolve_tenant)],
) -> StreamingResponse:
    body: dict[str, Any] = await request.json()

    messages = body.get("messages", [])
    history = _ui_messages_to_ollama_history(messages)
    pending_approval = _find_pending_approval(messages)

    safety_mode = body.get("safetyMode", "readonly")
    model = body.get("model") or DEFAULT_MODEL
    mode = body.get("mode", "ops")  # "ops" | "rag" — see docs/rag.md

    extra_context = ""
    rag_sources: list[dict] = []
    if mode == "rag" and history and history[-1]["role"] == "user":
        try:
            extra_context, rag_sources = await build_context(tenant, get_store(), history[-1]["content"])
        except EmbeddingError:
            # Empty index/embeddings backend unavailable → continue in
            # silent ops mode rather than breaking the conversation.
            pass

    enabled_tools = body.get("enabledTools")  # None = no runtime restriction (UI toggle, see docs/tools.md)
    enabled_tool_names = set(enabled_tools) if enabled_tools is not None else None

    events = run_agent_loop(
        tenant, history, safety_mode, model,
        pending_approval=pending_approval,
        extra_context=extra_context,
        rag_sources=rag_sources,
        enabled_tool_names=enabled_tool_names,
    )

    return StreamingResponse(
        encode_sse(events),
        headers=AISDK_STREAM_HEADERS,
    )
