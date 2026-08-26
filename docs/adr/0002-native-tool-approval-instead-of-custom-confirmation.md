# ADR 0002 — Use the AI SDK's native approval mechanism rather than a custom confirmation flow

## Status
Accepted

## Context
The initial plan for milestone M3 (confirmation flow for mutant/destructive commands) called for inventing a custom part (`data-confirmation`) and a manual round-trip via `addToolResult`, for lack of a known standard equivalent in the AI SDK protocol at planning time.

While verifying the actual implementation of the `ai@7.0.79` package (see [`protocol.md`](../protocol.md)) to prepare for M2, it turned out the protocol has a **native** tool approval mechanism: `tool-approval-request`/`tool-approval-response` chunks, `approval-requested`/`approval-responded` states on tool parts, and dedicated client helpers (`addToolApprovalResponse`, `ChatAddToolApproveResponseFunction`).

## Decision
M3 will use this native mechanism instead of inventing a custom protocol on top:
- Backend: emit `ApprovalRequired` (already present in `app/agent/events.py`) → encoded as `tool-approval-request` (already implemented in `app/stream/aisdk_protocol.py`, with a custom `data-approval-details` part for the human-readable summary/category, which have no standard equivalent).
- Frontend: use `useChat`'s `addToolApprovalResponse` rather than a repurposed `addToolResult`.
- Backend, when reconstructing history (`_extract_text`/its future replacement in `app/routers/chat.py`): detect a `dynamic-tool` part with `state: "approval-responded"` and no matching `output-available` → actually run the tool (`safety_mode="__confirmed__"`) before resuming the LLM loop.

## Consequences
- Less custom protocol surface to maintain — we follow a contract versioned by the AI SDK rather than a homegrown invention.
- `app/routers/chat.py::_find_pending_approval` looks for the `dynamic-tool` part in `approval-responded` state on the last assistant message to trigger post-approval execution — `_extract_text` deliberately stays limited to text for the rest of the history (see the documented limitation in `protocol.md`).

## Follow-up — spike validated (M3)

The unverified point mentioned above was tested: the full round-trip (`tool-approval-request` → `ConfirmCard` → `addToolApprovalResponse` → automatic resubmission via `sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses` → actual execution on the backend) works without a hitch with a Python backend, verified in-browser with a real Ollama model (confirmation, execution, and denial). No surprises on the protocol side at this stage.

A real friction point encountered, unrelated to the protocol itself: without explicit instructions, the LLM would try to simulate a confirmation in text instead of calling the tool — fixed by clarifying the system prompt (`app/agent/prompt.py`), not an architecture problem.
