"""
Agent tool-calling loop — protocol-agnostic: yields `AgentEvent`
(app/agent/events.py), with no knowledge of the SSE/AI SDK format. See
app/stream/aisdk_protocol.py for the encoding, and docs/protocol.md for why
this separation exists.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

from app.agent import events as ev
from app.agent.anonymizer import Anonymizer
from app.agent.guardrails import GuardrailAction, SafetyMode, decide
from app.agent.prompt import build_system_prompt
from app.agent.tools.registry import ToolContext, get_enabled_tools, get_tool, tool_to_ollama_schema
from app.config.schema import TenantConfig
from app.exec.factory import describe_executor, get_executor
from app.logging_config import get_audit_logger
from app.stream.chunks import ProviderError, ToolCall
from app.stream.providers import get_stream_chat_fn

_audit = get_audit_logger()

MAX_ROUNDS = 5
MAX_TOOL_RESULT_CHARS = 16_000


@dataclass
class PendingApproval:
    """
    The user's response to an ApprovalRequired from a previous turn —
    reconstructed by the router from the message history (a dynamic-tool
    part in "approval-responded" state). See docs/security-model.md.
    """
    tool_call_id: str
    tool_name: str
    input: dict
    approved: bool
    reason: str | None = None


def _truncate_for_context(result: dict, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """
    Serializes `result` to JSON and truncates it if too large for the LLM's
    context window. The full result is already sent to the frontend via
    ToolOutputAvailable — this only limits what goes back to Ollama.
    """
    raw = json.dumps(result, ensure_ascii=False)
    if len(raw) <= max_chars:
        return raw
    truncated = dict(result)
    for key in ("stdout", "output"):
        if key in truncated:
            val_json = json.dumps(truncated[key], ensure_ascii=False)
            if len(val_json) > max_chars // 2:
                truncated[key] = (
                    f"[PARTIAL_RESULT — {len(val_json)} chars, truncated. Summarize "
                    f"only what follows, don't re-run a command for the rest. "
                    f"Start: {val_json[:2000]}]"
                )
                raw2 = json.dumps(truncated, ensure_ascii=False)
                if len(raw2) <= max_chars:
                    return raw2
    return raw[:max_chars] + f"\n[PARTIAL_RESULT — {len(raw)} chars, truncated to {max_chars}.]"


def _is_tool_error(result: dict) -> bool:
    """
    Distinguishes a tool infrastructure error (missing argument, unknown
    tool — no command actually ran) from a command result that simply
    failed (kubectl ran but returned a non-zero returncode). The latter
    stays a ToolOutputAvailable: the LLM needs to see stdout/stderr to
    reason about the failure — it's not a protocol error.
    """
    return bool(result.get("error")) and "command" not in result


async def _execute_and_anonymize(tool_name: str, args: dict, ctx: ToolContext, anonymizer: Anonymizer, safety_mode: str) -> dict:
    tool = get_tool(tool_name)
    if tool is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        result = await tool.execute(args, ctx)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    if isinstance(result, dict) and "command" in result:
        # Transparency: where did this command actually run? Only on
        # results that represent a command that was actually executed (not
        # pre-execution validation errors).
        result.setdefault("executed_via", ctx.exec_target)
    return anonymizer.anonymize_result(tool_name, args, result, safety_mode)


async def run_agent_loop(
    tenant: TenantConfig,
    history: list[dict],  # [{role, content}, ...] Ollama format — already converted by the router
    safety_mode: SafetyMode,
    model: str,
    pending_approval: PendingApproval | None = None,
    extra_context: str = "",       # RAG context already retrieved by the router (RAG mode) — see docs/rag.md
    rag_sources: list[dict] | None = None,
    enabled_tool_names: set[str] | None = None,  # runtime restriction from the UI — see docs/tools.md
) -> AsyncGenerator[ev.AgentEvent, None]:
    yield ev.Start()

    if rag_sources:
        yield ev.RagSources(rag_sources)

    anonymizer = Anonymizer()
    anonymizer.start_turn()

    tools = get_enabled_tools(tenant, override_names=enabled_tool_names)
    tool_schemas = [tool_to_ollama_schema(t) for t in tools]
    allowed_tool_names = {t.name for t in tools}
    ctx = ToolContext(tenant=tenant, executor=get_executor(tenant), exec_target=describe_executor(tenant))
    # Which LLM backend answers this tenant's turns — see docs/llm-providers.md.
    stream_chat = get_stream_chat_fn(tenant)

    messages = [
        {"role": "system", "content": build_system_prompt(tenant, safety_mode, extra_context)}
    ] + history

    # ── Resolving a pending approval (see docs/security-model.md) ──
    # The user responded to an ApprovalRequired from a previous turn (a new
    # HTTP request, history reconstructed by the router). We actually
    # execute now — or refuse — before letting the LLM take over again.
    if pending_approval is not None:
        _audit.info(
            "approval_resolved tenant=%s tool=%s approved=%s",
            tenant.id, pending_approval.tool_name, pending_approval.approved,
        )
        if not pending_approval.approved:
            yield ev.ToolOutputDenied(pending_approval.tool_call_id)
            tool_result_content = json.dumps({
                "denied": True,
                "reason": pending_approval.reason or "Action denied by the user.",
            })
        else:
            result = await _execute_and_anonymize(
                pending_approval.tool_name, pending_approval.input, ctx, anonymizer, "__confirmed__"
            )
            if _is_tool_error(result):
                yield ev.ToolOutputError(pending_approval.tool_call_id, str(result["error"]))
            else:
                yield ev.ToolOutputAvailable(pending_approval.tool_call_id, result)
            tool_result_content = _truncate_for_context(result)

        messages = messages + [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {
                    "name": pending_approval.tool_name, "arguments": pending_approval.input,
                }}],
            },
            {"role": "tool", "content": tool_result_content},
        ]

    for _round in range(MAX_ROUNDS):
        text_id = str(uuid.uuid4())
        text_started = False
        response_text = ""
        tool_calls: list[ToolCall] = []

        async for chunk in stream_chat(messages, tool_schemas, model):
            if isinstance(chunk, ProviderError):
                if text_started:
                    yield ev.TextEnd(text_id)
                yield ev.ErrorEvent(chunk.message)
                yield ev.Finish()
                return
            if isinstance(chunk, ToolCall):
                tool_calls.append(chunk)
                continue
            if not text_started:
                yield ev.TextStart(text_id)
                text_started = True
            response_text += chunk.content
            yield ev.TextDelta(id=text_id, delta=chunk.content)

        if text_started:
            yield ev.TextEnd(text_id)

        if not tool_calls:
            yield ev.Finish()
            return

        tool_result_messages: list[dict] = []
        for tc in tool_calls:
            tool = get_tool(tc.name)

            if tool is None or tc.name not in allowed_tool_names:
                # The second case covers an LLM calling a tool that was
                # disabled at runtime for this conversation (not in the
                # tool_schemas sent) — get_tool() alone wouldn't know that,
                # we have to check explicitly against the actually allowed
                # set.
                error_text = f"Unknown or disabled tool for this conversation: {tc.name}"
                yield ev.ToolInputAvailable(tool_call_id=tc.id, tool_name=tc.name, input=tc.arguments)
                yield ev.ToolOutputError(tc.id, error_text)
                tool_result_messages.append({"role": "tool", "content": json.dumps({"error": error_text})})
                continue

            yield ev.ToolInputAvailable(tool_call_id=tc.id, tool_name=tc.name, input=tc.arguments)

            if tool.classify is not None:
                classification = tool.classify(tc.arguments)
                decision = decide(classification.category, safety_mode)
                _audit.info(
                    "guardrail tenant=%s tool=%s category=%s safety_mode=%s action=%s",
                    tenant.id, tc.name, classification.category.value, safety_mode, decision.action.value,
                )

                if decision.action == GuardrailAction.DENY:
                    yield ev.ToolOutputError(tc.id, decision.reason)
                    tool_result_messages.append(
                        {"role": "tool", "content": json.dumps({"error": decision.reason})}
                    )
                    continue

                if decision.action == GuardrailAction.CONFIRM:
                    # We can't continue without the user's response, which
                    # will arrive in a future HTTP request (see
                    # pending_approval above) — we stop the whole generator,
                    # not just this tool call.
                    yield ev.ApprovalRequired(
                        approval_id=f"appr_{tc.id}",
                        tool_call_id=tc.id,
                        summary=classification.label,
                        category=classification.category.value,
                    )
                    yield ev.Finish()
                    return

            result = await _execute_and_anonymize(tc.name, tc.arguments, ctx, anonymizer, safety_mode)

            if _is_tool_error(result):
                yield ev.ToolOutputError(tc.id, str(result["error"]))
            else:
                yield ev.ToolOutputAvailable(tc.id, result)

            tool_result_messages.append({"role": "tool", "content": _truncate_for_context(result)})

        messages = messages + [
            {
                "role": "assistant",
                "content": response_text,
                "tool_calls": [
                    {"function": {"name": tc.name, "arguments": tc.arguments}} for tc in tool_calls
                ],
            },
        ] + tool_result_messages

    yield ev.ErrorEvent("Maximum number of rounds reached without a final response.")
    yield ev.Finish()
