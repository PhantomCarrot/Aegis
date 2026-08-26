"""
AirLLM provider — runs a Hugging Face causal LM in-process, streaming its
weights layer by layer from disk (https://github.com/lyogavin/airllm)
instead of talking to an external chat server the way every other provider
does. Optional dependency — install with `uv sync --extra airllm` in
backend/ (see pyproject.toml); torch/transformers/accelerate aren't pulled
in otherwise.

AirLLM has no chat-completions API and no native function-calling: its
whole surface is `AutoModel.from_pretrained(...).generate()`, a thin
wrapper around `transformers`' own `generate()` (verified by reading
airllm 3.2.0's source — `AirLLMBaseModel.generate()` just delegates to
`self.model.generate()`). To keep tool-calling working the same way it
does for Ollama/LM Studio — Aegis's guardrail/confirmation flow sits on
top of tool calls, so a text-only fallback would silently break every
tenant that switches to this provider — this provider prompts the model
itself: available tools are described in the system prompt along with a
fixed delimited format to emit a call in, and the streamed output is
scanned for that format as it's generated (`_TOOL_CALL_OPEN`/`_CLOSE`
below). This is inherently less reliable than a model's native
tool-calling — it depends on the model actually following the
instructions — but it's the only option this library leaves open. See
docs/llm-providers.md.

Not live-tested end to end (needs a real model download and, on Apple
Silicon, AirLLM's separate `mlx` extra — untested here); the request/
response shape below is verified against `transformers`' own documented
`TextIteratorStreamer` usage pattern and against airllm's actual source.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncGenerator

from app.config.schema import AirLLMConfig
from app.stream.chunks import ProviderError, TextChunk, ToolCall

_TOOL_CALL_OPEN = "<tool_call>"
_TOOL_CALL_CLOSE = "</tool_call>"

# One loaded model per (model, device, compression) — loading/sharding a
# checkpoint is the expensive part AirLLM exists to make bearable, so it's
# kept warm for the life of the process rather than reloaded per request.
_model_cache: dict[tuple, Any] = {}
_tokenizer_cache: dict[str, Any] = {}
_load_lock = threading.Lock()


def _get_model_and_tokenizer(config: AirLLMConfig) -> tuple[Any, Any]:
    # Imported lazily: torch/transformers/airllm are an optional extra
    # (`uv sync --extra airllm`), not a hard dependency of the base
    # install — importing them at module load time would break every
    # tenant that doesn't use this provider, just by existing in the repo.
    from airllm import AutoModel
    from transformers import AutoTokenizer

    key = (config.model, config.device, config.compression)
    with _load_lock:
        if key not in _model_cache:
            _model_cache[key] = AutoModel.from_pretrained(
                config.model,
                device=config.device,
                compression=config.compression,
                max_seq_len=config.max_seq_len,
            )
        if config.model not in _tokenizer_cache:
            _tokenizer_cache[config.model] = AutoTokenizer.from_pretrained(config.model)
    return _model_cache[key], _tokenizer_cache[config.model]


def _tools_instructions(tools: list[dict]) -> str:
    if not tools:
        return ""
    tool_lines = "\n".join(
        f"- {t['function']['name']}: {t['function']['description']} "
        f"— parameters (JSON Schema): {json.dumps(t['function']['parameters'])}"
        for t in tools
    )
    return (
        "\n\nYou have access to these tools:\n"
        f"{tool_lines}\n\n"
        "To call one, respond with EXACTLY this and nothing else in your reply:\n"
        f"{_TOOL_CALL_OPEN}\n"
        '{"name": "<tool name>", "arguments": {...}}\n'
        f"{_TOOL_CALL_CLOSE}\n"
        "Only one tool call per turn. If you don't need a tool, just answer normally — "
        "never use that format for anything other than an actual tool call."
    )


def _flatten_tool_history(messages: list[dict]) -> list[dict]:
    """
    AirLLM never sees a structured tool call back (no ids to preserve,
    unlike the OpenAI-style round trip LM Studio needs) — fold any
    assistant `tool_calls` entry plus the tool-result message(s) that
    follow it (loop.py always emits them immediately after, in order) into
    plain text, in the same delimited format the model is instructed to
    emit itself. Keeps the model's own past tool calls legible to itself
    across turns without inventing a second protocol just for history.
    """
    out: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            calls_text = "\n".join(
                f"{_TOOL_CALL_OPEN}\n"
                f"{json.dumps({'name': tc['function']['name'], 'arguments': tc['function']['arguments']})}\n"
                f"{_TOOL_CALL_CLOSE}"
                for tc in msg["tool_calls"]
            )
            content = (msg.get("content") or "").strip()
            out.append({"role": "assistant", "content": (content + "\n" + calls_text).strip()})
            i += 1
            results = []
            while i < len(messages) and messages[i].get("role") == "tool":
                results.append(messages[i].get("content", ""))
                i += 1
            if results:
                out.append({"role": "user", "content": "Tool result(s):\n" + "\n".join(results)})
            continue
        out.append({"role": msg["role"], "content": msg.get("content", "")})
        i += 1
    return out


def _build_prompt(tokenizer, messages: list[dict], tools: list[dict]) -> str:
    flat = _flatten_tool_history(messages)
    instructions = _tools_instructions(tools)
    if instructions:
        if flat and flat[0]["role"] == "system":
            flat[0] = {**flat[0], "content": flat[0]["content"] + instructions}
        else:
            flat.insert(0, {"role": "system", "content": instructions.strip()})
    return tokenizer.apply_chat_template(flat, tokenize=False, add_generation_prompt=True)


async def _scan_for_tool_calls(pieces: AsyncGenerator[str, None]) -> AsyncGenerator[TextChunk | ToolCall, None]:
    """
    The actual tag-scanning state machine, pulled out of `stream_chat()` so
    it's testable on its own — as a pure function over an async iterable of
    text pieces, no model loading, no threading. `pieces` stands in for
    `TextIteratorStreamer` (real usage: `stream_chat()` below wraps the
    streamer's blocking iteration into exactly this shape).
    """
    buffer = ""
    in_tool_call = False
    tool_call_counter = 0

    async for piece in pieces:
        buffer += piece

        while True:
            if not in_tool_call:
                open_idx = buffer.find(_TOOL_CALL_OPEN)
                if open_idx == -1:
                    # Hold back a tail as long as the open tag minus one
                    # char, in case it's split across two pieces.
                    safe_len = max(0, len(buffer) - (len(_TOOL_CALL_OPEN) - 1))
                    if safe_len > 0:
                        yield TextChunk(buffer[:safe_len])
                        buffer = buffer[safe_len:]
                    break
                if open_idx > 0:
                    yield TextChunk(buffer[:open_idx])
                buffer = buffer[open_idx + len(_TOOL_CALL_OPEN):]
                in_tool_call = True
                continue
            else:
                close_idx = buffer.find(_TOOL_CALL_CLOSE)
                if close_idx == -1:
                    break
                raw = buffer[:close_idx].strip()
                buffer = buffer[close_idx + len(_TOOL_CALL_CLOSE):]
                in_tool_call = False
                try:
                    parsed = json.loads(raw)
                    tool_call_counter += 1
                    yield ToolCall(
                        id=f"call_{tool_call_counter}",
                        name=parsed.get("name", ""),
                        arguments=parsed.get("arguments", {}),
                    )
                except json.JSONDecodeError:
                    # The model didn't follow the format — surface the raw
                    # text rather than silently dropping it.
                    yield TextChunk(f"{_TOOL_CALL_OPEN}{raw}{_TOOL_CALL_CLOSE}")
                continue

    # Flush what's left: trailing text, or an unterminated tool_call block
    # the model never closed (fail open — show it raw rather than eat it
    # silently).
    if buffer:
        yield TextChunk(f"{_TOOL_CALL_OPEN}{buffer}" if in_tool_call else buffer)


def _run_generate(model, tokenizer, prompt: str, config: AirLLMConfig, streamer, error_box: list) -> None:
    """Runs on a background thread — model.generate() is a blocking, CPU/GPU-bound call."""
    try:
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=config.max_seq_len)
        if config.device != "cpu":
            inputs = {k: v.to(config.device) for k, v in inputs.items()}
        model.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs.get("attention_mask"),
            max_new_tokens=config.max_new_tokens,
            streamer=streamer,
        )
    except Exception as e:  # noqa: BLE001 - reported to the caller via error_box, not swallowed
        error_box.append(e)
        # Without this, an exception here (e.g. OOM mid-generation) would
        # leave the consuming `next(streamer)` loop below blocked forever —
        # generate() failing is the one path that never reaches the queue's
        # normal stream_end signal on its own.
        streamer.end()


async def stream_chat(
    messages: list[dict],
    tools: list[dict],
    model: str,  # noqa: ARG001 - ignored: AirLLM's model is fixed per tenant (config.model
                 # below) — loading is too expensive to swap per request. Kept in the
                 # signature so every provider's stream_chat() has the same shape, see
                 # app/stream/providers.py.
    config: AirLLMConfig | None = None,
) -> AsyncGenerator[TextChunk | ToolCall | ProviderError, None]:
    if config is None:
        yield ProviderError("AirLLM provider called without a config (llm.airllm) — this is a bug, not a user error.")
        return

    try:
        from transformers import TextIteratorStreamer
    except ImportError:
        yield ProviderError(
            "AirLLM's dependencies (torch/transformers/airllm) aren't installed — "
            "run `uv sync --extra airllm` in backend/. See docs/llm-providers.md."
        )
        return

    try:
        model_obj, tokenizer = await asyncio.to_thread(_get_model_and_tokenizer, config)
    except Exception as e:
        yield ProviderError(f"AirLLM failed to load '{config.model}': {type(e).__name__}: {e}")
        return

    prompt = _build_prompt(tokenizer, messages, tools)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    error_box: list[Exception] = []

    thread = threading.Thread(
        target=_run_generate, args=(model_obj, tokenizer, prompt, config, streamer, error_box)
    )
    thread.start()

    async def _pieces() -> AsyncGenerator[str, None]:
        while True:
            try:
                # TextIteratorStreamer is a blocking iterator — pull it off
                # the event loop so other requests keep streaming meanwhile.
                yield await asyncio.to_thread(next, streamer)
            except StopIteration:
                return

    try:
        async for chunk in _scan_for_tool_calls(_pieces()):
            yield chunk

        if error_box:
            e = error_box[0]
            yield ProviderError(f"AirLLM generation error: {type(e).__name__}: {e}")
    finally:
        thread.join(timeout=5)
