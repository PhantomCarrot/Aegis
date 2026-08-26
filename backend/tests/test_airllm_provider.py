"""
Tests for the AirLLM provider's prompt-engineered tool-calling — the parts
that don't need torch/transformers/airllm actually installed (that's an
optional extra, `uv sync --extra airllm`, see pyproject.toml).

`_scan_for_tool_calls` is the tag-scanning state machine that turns a
stream of raw text pieces into TextChunk/ToolCall — the same shape a real
model's streamed output goes through, but here fed by hand to exercise tag
boundaries split across pieces without needing a real model.
"""
from app.stream.airllm_provider import (
    _TOOL_CALL_CLOSE,
    _TOOL_CALL_OPEN,
    _flatten_tool_history,
    _scan_for_tool_calls,
    _tools_instructions,
)
from app.stream.chunks import TextChunk, ToolCall


async def _aiter(pieces: list[str]):
    for p in pieces:
        yield p


async def _collect(pieces: list[str]) -> list:
    return [chunk async for chunk in _scan_for_tool_calls(_aiter(pieces))]


async def test_plain_text_with_no_tool_call():
    # Chunk boundaries don't necessarily match the input pieces 1:1 — a
    # short tail is held back in case it's the start of a split tag (see
    # test_tool_call_tag_split_across_pieces) — only the concatenated text
    # is guaranteed.
    chunks = await _collect(["Hello, ", "how can I help?"])
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert "".join(c.content for c in chunks) == "Hello, how can I help?"


async def test_tool_call_in_a_single_piece():
    piece = f'{_TOOL_CALL_OPEN}\n{{"name": "kubectl_get", "arguments": {{"resource": "pods"}}}}\n{_TOOL_CALL_CLOSE}'
    chunks = await _collect([piece])
    assert len(chunks) == 1
    assert isinstance(chunks[0], ToolCall)
    assert chunks[0].name == "kubectl_get"
    assert chunks[0].arguments == {"resource": "pods"}


async def test_tool_call_tag_split_across_pieces():
    """The whole point of the buffering: a streamed model emits a handful of
    tokens at a time, so the tag can land split across pieces."""
    full = f'{_TOOL_CALL_OPEN}\n{{"name": "kubectl_get", "arguments": {{}}}}\n{_TOOL_CALL_CLOSE}'
    # Split into small, deliberately tag-unaligned pieces.
    pieces = [full[i:i + 3] for i in range(0, len(full), 3)]
    chunks = await _collect(pieces)
    assert len(chunks) == 1
    assert isinstance(chunks[0], ToolCall)
    assert chunks[0].name == "kubectl_get"


async def test_text_before_and_after_tool_call():
    piece = (
        f'Let me check that.\n{_TOOL_CALL_OPEN}\n'
        f'{{"name": "kubectl_get", "arguments": {{}}}}\n{_TOOL_CALL_CLOSE}'
    )
    chunks = await _collect([piece])
    text_chunks = [c for c in chunks if isinstance(c, TextChunk)]
    tool_calls = [c for c in chunks if isinstance(c, ToolCall)]
    assert len(tool_calls) == 1
    assert "Let me check that." in "".join(c.content for c in text_chunks)


async def test_multiple_tool_calls_get_distinct_ids():
    piece = (
        f'{_TOOL_CALL_OPEN}\n{{"name": "a", "arguments": {{}}}}\n{_TOOL_CALL_CLOSE}'
        f'{_TOOL_CALL_OPEN}\n{{"name": "b", "arguments": {{}}}}\n{_TOOL_CALL_CLOSE}'
    )
    chunks = await _collect([piece])
    tool_calls = [c for c in chunks if isinstance(c, ToolCall)]
    assert [c.name for c in tool_calls] == ["a", "b"]
    assert len({c.id for c in tool_calls}) == 2


async def test_malformed_tool_call_json_falls_back_to_text():
    """The model didn't follow the format — fail open, don't silently drop the output."""
    piece = f"{_TOOL_CALL_OPEN}\nnot valid json\n{_TOOL_CALL_CLOSE}"
    chunks = await _collect([piece])
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert "not valid json" in "".join(c.content for c in chunks)


async def test_unterminated_tool_call_is_flushed_as_text():
    """Model runs out of tokens mid tool-call — fail open rather than hang or drop it."""
    piece = f'{_TOOL_CALL_OPEN}\n{{"name": "kubectl_get"'
    chunks = await _collect([piece])
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert _TOOL_CALL_OPEN in "".join(c.content for c in chunks)


def test_tools_instructions_empty_when_no_tools():
    assert _tools_instructions([]) == ""


def test_tools_instructions_includes_name_and_delimiters():
    tools = [{"function": {"name": "kubectl_get", "description": "lists things", "parameters": {}}}]
    text = _tools_instructions(tools)
    assert "kubectl_get" in text
    assert "lists things" in text
    assert _TOOL_CALL_OPEN in text
    assert _TOOL_CALL_CLOSE in text


def test_flatten_tool_history_folds_tool_calls_into_text():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "list pods"},
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": "kubectl_get", "arguments": {"resource": "pods"}}}],
        },
        {"role": "tool", "content": '{"stdout": "no resources found"}'},
    ]
    flat = _flatten_tool_history(messages)
    assert [m["role"] for m in flat] == ["system", "user", "assistant", "user"]
    assert _TOOL_CALL_OPEN in flat[2]["content"]
    assert "kubectl_get" in flat[2]["content"]
    assert "no resources found" in flat[3]["content"]


def test_flatten_tool_history_leaves_plain_messages_untouched():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert _flatten_tool_history(messages) == messages
