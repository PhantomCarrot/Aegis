"""
Internal events emitted by the agent loop (app/agent/loop.py).

Deliberately protocol-agnostic: these dataclasses know nothing about the
SSE/AI SDK format. Encoding to that format lives exclusively in
app/stream/aisdk_protocol.py — see docs/protocol.md. This isolates the
"the AI SDK protocol changes" risk to a single, independently testable file.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Start:
    """Start of a response turn."""


@dataclass
class TextStart:
    """
    Opens a text block identified by `id`. The AI SDK protocol is strict on
    the client side: a `text-delta` without a prior `text-start` for the
    same id throws — verified in node_modules/ai (see protocol.md).
    """
    id: str


@dataclass
class TextDelta:
    """Text fragment streamed by the LLM. `id` groups deltas belonging to the same text block."""
    id: str
    delta: str


@dataclass
class TextEnd:
    """Closes the text block opened by TextStart(id) — same client-side strictness constraint."""
    id: str


@dataclass
class ToolInputAvailable:
    """The LLM decided to call a tool, with its full arguments (no partial streaming)."""
    tool_call_id: str
    tool_name: str
    input: dict = field(default_factory=dict)


@dataclass
class ToolOutputAvailable:
    tool_call_id: str
    output: dict


@dataclass
class ToolOutputError:
    tool_call_id: str
    error_text: str


@dataclass
class ApprovalRequired:
    """
    The tool was classified mutant/destructive by the guardrails and the
    active safety mode requires human confirmation before execution — see
    docs/security-model.md. `approval_id` is echoed back by the client in
    its next message (a `tool-approval-response` part).
    """
    approval_id: str
    tool_call_id: str
    summary: str
    category: str  # "mutant" | "destructive"


@dataclass
class ToolOutputDenied:
    """The user explicitly denied the execution requested by ApprovalRequired."""
    tool_call_id: str


@dataclass
class RagSources:
    """
    Documentation sources used to enrich the context in RAG mode (see
    docs/rag.md) — emitted once at the start of a turn, before the text.
    """
    sources: list[dict] = field(default_factory=list)


@dataclass
class ErrorEvent:
    error_text: str


@dataclass
class Finish:
    """End of turn — the loop has nothing left to stream."""


AgentEvent = (
    Start
    | TextStart
    | TextDelta
    | TextEnd
    | ToolInputAvailable
    | ToolOutputAvailable
    | ToolOutputError
    | ToolOutputDenied
    | ApprovalRequired
    | RagSources
    | ErrorEvent
    | Finish
)
