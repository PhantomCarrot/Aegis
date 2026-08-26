"""
Tests for the LM Studio provider: the internal → OpenAI message-shape
translation, and the streamed chat-completions response parsing (tool-call
argument accumulation across chunks — the one genuinely different piece
from Ollama's provider, since OpenAI-style streaming sends `function.
arguments` as incremental string fragments instead of one shot).
"""
import json

import httpx

from app.stream import lmstudio_provider
from app.stream.chunks import ProviderError, TextChunk, ToolCall
from app.stream.lmstudio_provider import _to_openai_messages

# ─── _to_openai_messages ────────────────────────────────────────────────────

def test_translates_plain_messages_unchanged():
    messages = [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
    assert _to_openai_messages(messages) == messages


def test_synthesizes_ids_and_links_tool_result():
    messages = [
        {"role": "user", "content": "list pods"},
        {
            "role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": "kubectl_get", "arguments": {"resource": "pods"}}}],
        },
        {"role": "tool", "content": '{"stdout": "ok"}'},
    ]
    out = _to_openai_messages(messages)

    assert out[0] == {"role": "user", "content": "list pods"}
    assistant = out[1]
    assert assistant["role"] == "assistant"
    assert len(assistant["tool_calls"]) == 1
    call = assistant["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "kubectl_get"
    # OpenAI wants arguments as a JSON *string*, not a dict.
    assert json.loads(call["function"]["arguments"]) == {"resource": "pods"}

    tool_msg = out[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == call["id"]
    assert tool_msg["content"] == '{"stdout": "ok"}'


def test_multiple_tool_calls_pair_positionally_with_multiple_results():
    messages = [
        {
            "role": "assistant", "content": "",
            "tool_calls": [
                {"function": {"name": "a", "arguments": {}}},
                {"function": {"name": "b", "arguments": {}}},
            ],
        },
        {"role": "tool", "content": "result a"},
        {"role": "tool", "content": "result b"},
    ]
    out = _to_openai_messages(messages)
    ids = [c["id"] for c in out[0]["tool_calls"]]
    assert out[1]["tool_call_id"] == ids[0]
    assert out[1]["content"] == "result a"
    assert out[2]["tool_call_id"] == ids[1]
    assert out[2]["content"] == "result b"


# ─── stream_chat ─────────────────────────────────────────────────────────────

def _sse_lines(*chunks: dict) -> list[str]:
    lines = [f"data: {json.dumps(c)}" for c in chunks]
    lines.append("data: [DONE]")
    return lines


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str], body: bytes = b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    def __init__(self, lines: list[str], status_code: int = 200, *, timeout=None):
        self._lines = lines
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None):
        return _FakeStreamCtx(_FakeStreamResponse(self._status_code, self._lines))


async def test_stream_chat_yields_text_deltas(monkeypatch):
    lines = _sse_lines(
        {"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": ", world"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    )
    monkeypatch.setattr(lmstudio_provider.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(lines))

    chunks = [c async for c in lmstudio_provider.stream_chat([{"role": "user", "content": "hi"}], [], "some-model")]
    text = [c for c in chunks if isinstance(c, TextChunk)]
    assert "".join(c.content for c in text) == "Hello, world"


async def test_stream_chat_accumulates_tool_call_arguments_across_chunks(monkeypatch):
    """OpenAI-style streaming: function.arguments arrives as JSON string
    fragments across several chunks, keyed by `index` — must be
    concatenated and parsed once, not per fragment."""
    lines = _sse_lines(
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_abc", "function": {"name": "kubectl_get", "arguments": ""}}
        ]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"resource"'}}
        ]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": ': "pods"}'}}
        ]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    )
    monkeypatch.setattr(lmstudio_provider.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(lines))

    chunks = [c async for c in lmstudio_provider.stream_chat([{"role": "user", "content": "hi"}], [], "some-model")]
    tool_calls = [c for c in chunks if isinstance(c, ToolCall)]
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_abc"
    assert tool_calls[0].name == "kubectl_get"
    assert tool_calls[0].arguments == {"resource": "pods"}


async def test_stream_chat_handles_multiple_concurrent_tool_calls(monkeypatch):
    lines = _sse_lines(
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_a", "function": {"name": "a", "arguments": "{}"}},
            {"index": 1, "id": "call_b", "function": {"name": "b", "arguments": "{}"}},
        ]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    )
    monkeypatch.setattr(lmstudio_provider.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(lines))

    chunks = [c async for c in lmstudio_provider.stream_chat([{"role": "user", "content": "hi"}], [], "some-model")]
    tool_calls = [c for c in chunks if isinstance(c, ToolCall)]
    assert [c.name for c in tool_calls] == ["a", "b"]


async def test_stream_chat_reports_http_error(monkeypatch):
    class _ErrClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json=None):
            body = json_lib.dumps({"error": "boom"}).encode()
            return _FakeStreamCtx(_FakeStreamResponse(500, [], body=body))

    import json as json_lib
    monkeypatch.setattr(lmstudio_provider.httpx, "AsyncClient", lambda timeout=None: _ErrClient())

    chunks = [c async for c in lmstudio_provider.stream_chat([{"role": "user", "content": "hi"}], [], "some-model")]
    assert len(chunks) == 1
    assert isinstance(chunks[0], ProviderError)
    assert "500" in chunks[0].message


async def test_stream_chat_reports_connection_error(monkeypatch):
    class _RefusingClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(lmstudio_provider.httpx, "AsyncClient", lambda timeout=None: _RefusingClient())

    chunks = [c async for c in lmstudio_provider.stream_chat([{"role": "user", "content": "hi"}], [], "some-model")]
    assert len(chunks) == 1
    assert isinstance(chunks[0], ProviderError)
    assert "unreachable" in chunks[0].message
