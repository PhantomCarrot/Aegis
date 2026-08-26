"""
Provider-agnostic streaming chunk types, shared by every `app/stream/*_provider.py`
module and consumed by `app/agent/loop.py`. Kept in their own module rather
than owned by one provider (e.g. `ollama_provider.py`) so neither the loop
nor any other provider has to depend on Ollama's module to know these
shapes — see docs/llm-providers.md.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextChunk:
    content: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderError:
    message: str


Chunk = TextChunk | ToolCall | ProviderError
