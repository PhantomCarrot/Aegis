"""
Resolves which provider's `stream_chat()` answers chat turns for a given
tenant, from `tenant.llm.provider` (see app/config/schema.py). Every
provider module (ollama_provider.py, lmstudio_provider.py,
airllm_provider.py) has the same shape — `stream_chat(messages, tools,
model, **provider_specific_kwarg) -> AsyncGenerator[Chunk]` — so
app/agent/loop.py never needs to know which one it's talking to; it just
calls whatever this returns. See docs/llm-providers.md.
"""
from __future__ import annotations

from typing import AsyncGenerator, Callable

from app.config.schema import TenantConfig
from app.stream import airllm_provider, lmstudio_provider, ollama_provider
from app.stream.chunks import Chunk

StreamChatFn = Callable[[list[dict], list[dict], str], AsyncGenerator[Chunk, None]]


def get_stream_chat_fn(tenant: TenantConfig) -> StreamChatFn:
    provider = tenant.llm.provider

    if provider == "ollama":
        return lambda messages, tools, model: ollama_provider.stream_chat(
            messages, tools, model, ollama_url=tenant.ollama.url
        )

    if provider == "lmstudio":
        return lambda messages, tools, model: lmstudio_provider.stream_chat(
            messages, tools, model, base_url=tenant.llm.lmstudio.url
        )

    if provider == "airllm":
        return lambda messages, tools, model: airllm_provider.stream_chat(
            messages, tools, model, config=tenant.llm.airllm
        )

    raise ValueError(f"Unknown llm.provider for tenant '{tenant.id}': {provider!r}")  # pragma: no cover
