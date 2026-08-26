"""
Markdown document chunking for RAG indexing.

Splits by heading structure rather than a naive blind sliding window: each
chunk is prefixed with its "breadcrumb" (e.g. "Cluster > Pods") so the
hierarchical context isn't lost once it's isolated from the rest of the
document — see docs/rag.md. Size expressed in characters as an approximate
proxy for token count (~4 chars/token in French/English).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

DEFAULT_MAX_CHARS = 2000
DEFAULT_OVERLAP_CHARS = 200


@dataclass
class Chunk:
    text: str          # content, already prefixed with the breadcrumb
    heading_path: str  # e.g. "Cluster > Pods" (empty if the doc has no headings)
    chunk_index: int


def _split_by_headings(markdown: str) -> list[tuple[list[str], str]]:
    """Returns a list of (heading_path, section_content)."""
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(([title for _, title in stack], content))

    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if not m:
            current_lines.append(line)
            continue
        flush()
        current_lines = []
        level = len(m.group(1))
        title = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
    flush()

    if not sections and markdown.strip():
        sections.append(([], markdown.strip()))
    return sections


def chunk_markdown(
    markdown: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """
    Splits a Markdown document into chunks with a heading breadcrumb. A
    section that's too long is re-split with a sliding window, keeping the
    same breadcrumb on each piece.
    """
    chunks: list[Chunk] = []
    idx = 0
    for path, content in _split_by_headings(markdown):
        breadcrumb = " > ".join(path)
        prefix = f"{breadcrumb}\n\n" if breadcrumb else ""

        if len(content) <= max_chars:
            chunks.append(Chunk(text=f"{prefix}{content}", heading_path=breadcrumb, chunk_index=idx))
            idx += 1
            continue

        start = 0
        while start < len(content):
            end = start + max_chars
            piece = content[start:end]
            chunks.append(Chunk(text=f"{prefix}{piece}", heading_path=breadcrumb, chunk_index=idx))
            idx += 1
            if end >= len(content):
                break
            start = end - overlap_chars

    return chunks
