"""
Tests for the AgentEvent → AI SDK UI Message Stream Protocol encoder.

Assertions on the exact format (headers, "data: ...\\n\\n", "[DONE]") are
deliberately strict: this module encodes an external contract (what
node_modules/ai expects), not an internal implementation detail — see
docs/protocol.md.
"""
import json

from app.agent import events as ev
from app.stream.aisdk_protocol import AISDK_STREAM_HEADERS, encode_sse


async def _events_to_list(*events: ev.AgentEvent) -> list[str]:
    async def gen():
        for e in events:
            yield e

    return [chunk async for chunk in encode_sse(gen())]


def _parse(sse_line: str) -> dict | None:
    assert sse_line.endswith("\n\n")
    payload = sse_line[len("data: "):-2]
    if payload == "[DONE]":
        return None
    return json.loads(payload)



async def test_headers_match_ai_sdk_contract():
    assert AISDK_STREAM_HEADERS == {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "x-vercel-ai-ui-message-stream": "v1",
        "x-accel-buffering": "no",
    }


async def test_every_line_is_data_prefixed_and_double_newline_terminated():
    lines = await _events_to_list(ev.Start(), ev.Finish())
    for line in lines:
        assert line.startswith("data: ")
        assert line.endswith("\n\n")


async def test_stream_always_ends_with_done_sentinel():
    lines = await _events_to_list(ev.Start(), ev.Finish())
    assert lines[-1] == "data: [DONE]\n\n"


async def test_start_emits_start_and_start_step():
    lines = await _events_to_list(ev.Start())
    chunks = [_parse(line) for line in lines[:-1]]  # excludes [DONE]
    assert chunks == [{"type": "start"}, {"type": "start-step"}]


async def test_text_lifecycle_is_start_delta_end():
    lines = await _events_to_list(
        ev.TextStart(id="t1"),
        ev.TextDelta(id="t1", delta="Hello"),
        ev.TextDelta(id="t1", delta=" !"),
        ev.TextEnd(id="t1"),
    )
    chunks = [_parse(line) for line in lines[:-1]]
    assert chunks == [
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "Hello"},
        {"type": "text-delta", "id": "t1", "delta": " !"},
        {"type": "text-end", "id": "t1"},
    ]


async def test_tool_input_available_is_marked_dynamic():
    lines = await _events_to_list(
        ev.ToolInputAvailable(tool_call_id="call_1", tool_name="kubectl_get", input={"resource": "pods"})
    )
    chunk = _parse(lines[0])
    assert chunk == {
        "type": "tool-input-available",
        "toolCallId": "call_1",
        "toolName": "kubectl_get",
        "input": {"resource": "pods"},
        "dynamic": True,
    }


async def test_tool_output_available():
    lines = await _events_to_list(ev.ToolOutputAvailable(tool_call_id="call_1", output={"stdout": "ok"}))
    assert _parse(lines[0]) == {
        "type": "tool-output-available",
        "toolCallId": "call_1",
        "output": {"stdout": "ok"},
    }


async def test_tool_output_error():
    lines = await _events_to_list(ev.ToolOutputError(tool_call_id="call_1", error_text="boom"))
    assert _parse(lines[0]) == {
        "type": "tool-output-error",
        "toolCallId": "call_1",
        "errorText": "boom",
    }


async def test_approval_required_emits_request_plus_custom_data_part():
    lines = await _events_to_list(
        ev.ApprovalRequired(
            approval_id="appr_1", tool_call_id="call_1", summary="Delete pod foo", category="destructive"
        )
    )
    chunks = [_parse(line) for line in lines[:-1]]
    assert chunks == [
        {"type": "tool-approval-request", "approvalId": "appr_1", "toolCallId": "call_1"},
        {
            "type": "data-approval-details",
            "id": "appr_1",
            "data": {"summary": "Delete pod foo", "category": "destructive"},
        },
    ]


async def test_error_event():
    lines = await _events_to_list(ev.ErrorEvent(error_text="Ollama inaccessible"))
    assert _parse(lines[0]) == {"type": "error", "errorText": "Ollama inaccessible"}


async def test_finish_emits_finish_step_and_finish():
    lines = await _events_to_list(ev.Finish())
    chunks = [_parse(line) for line in lines[:-1]]
    assert chunks == [{"type": "finish-step"}, {"type": "finish"}]


async def test_full_round_trip_matches_expected_sequence():
    """A full turn: start → text → tool call → response → finish."""
    lines = await _events_to_list(
        ev.Start(),
        ev.TextStart(id="t1"),
        ev.TextDelta(id="t1", delta="Checking the pods."),
        ev.TextEnd(id="t1"),
        ev.ToolInputAvailable(tool_call_id="call_1", tool_name="kubectl_get", input={"resource": "pods"}),
        ev.ToolOutputAvailable(tool_call_id="call_1", output={"stdout": "no resources found"}),
        ev.Finish(),
    )
    types = [_parse(line)["type"] for line in lines[:-1]]  # type: ignore[index]
    assert types == [
        "start", "start-step",
        "text-start", "text-delta", "text-end",
        "tool-input-available", "tool-output-available",
        "finish-step", "finish",
    ]
